"""
Réglages d'analyse, stockés en base et modifiables depuis la page Réglages.

Valeurs par défaut :
- référence principale : QQQ (Nasdaq 100), dividendes nets d'une retenue de 15 % ;
- seconde référence : IWDA.AS (MSCI World, capitalisant, coté en EUR), retenue 0 % ;
- taux sans risque : EONIA avant le 01/10/2019, €STR ensuite ;
- volatilité glissante sur 63 séances (environ 3 mois) ;
- covariance de Ledoit-Wolf à cible corrélation constante (page Diversification) ;
- valorisation : k commun par devise = taux d'État à 10 ans + prime de risque de 5 % (β = 1),
  horizon de 10 ans, croissance terminale de 2 %, FCF de départ lissé sur 3 exercices,
  rémunération en actions retranchée (voir METHODE.md).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from .models import Setting


class Reference(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=80)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    withholding: Decimal = Field(ge=0, le=Decimal("0.5"))      # 0,15 = 15 %

    @field_validator("ticker")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class AnalysisSettings(BaseModel):
    reference_1: Reference = Reference(ticker="QQQ", name="Nasdaq 100 (QQQ)", currency="USD",
                                       withholding=Decimal("0.15"))
    reference_2: Reference = Reference(ticker="IWDA.AS", name="MSCI World (IWDA)", currency="EUR",
                                       withholding=Decimal("0"))
    rf_mode: Literal["estr", "fixe", "zero"] = "estr"
    rf_fixed_rate: Decimal | None = Field(default=None, ge=Decimal("-5"), le=Decimal("20"))   # en %
    rolling_window: int = Field(default=63, ge=21, le=252)
    # Estimateur de covariance de la page Diversification (voir terminal/covariance.py).
    covariance: Literal["lw_cc", "lw_id", "empirique"] = "lw_cc"
    # Valorisation (page Valorisation, terminal/dcf.py). Taux en fraction : 0,05 = 5 %.
    k_mode: Literal["devise", "medaf"] = "devise"
    erp: Decimal = Field(default=Decimal("0.05"), ge=0, le=Decimal("0.15"))
    k_manual: dict[str, Decimal] = Field(default_factory=dict)          # k commun saisi par devise
    g_term: Decimal = Field(default=Decimal("0.02"), ge=Decimal("-0.05"), le=Decimal("0.06"))
    horizon: int = Field(default=10, ge=1, le=30)
    fcf_years: int = Field(default=3, ge=1, le=5)
    sbc_deduct: bool = True

    @field_validator("k_manual")
    @classmethod
    def _k_manual(cls, v: dict[str, Decimal]) -> dict[str, Decimal]:
        out = {}
        for cur, k in v.items():
            if len(cur) != 3 or not cur.isalpha() or not (Decimal("0") < k <= Decimal("0.3")):
                raise ValueError(f"k manuel invalide pour {cur} : devise sur 3 lettres, k entre 0 et 30 %")
            out[cur.upper()] = k
        return out

    def reference(self, i: int) -> Reference:
        return self.reference_1 if i == 1 else self.reference_2


KEY = "analysis"


def load(s: Session) -> AnalysisSettings:
    row = s.get(Setting, KEY)
    return AnalysisSettings.model_validate(json.loads(row.value)) if row else AnalysisSettings()


def save(s: Session, settings: AnalysisSettings) -> None:
    row = s.get(Setting, KEY) or Setting(key=KEY)
    row.value = settings.model_dump_json()
    s.add(row)
    s.commit()
