"""
Rendement du Treasury américain à 10 ans (FRED, Banque fédérale de Saint-Louis). Seul fichier
qui appelle FRED. Série DGS10, CSV public sans clé ; « . » marque un jour sans cotation.
FRED ne répond pas à certains User-Agent personnalisés (requête bloquée jusqu'au délai) :
on s'annonce comme un navigateur compatible.
"""

from __future__ import annotations

import csv
import io
import urllib.error
import urllib.request
from datetime import date

import pandas as pd

from ..errors import ProviderUnavailable
from .base import PriceSeries, clean_series
from .rates import RateProvider

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10&cosd={start}&coed={end}"
SOURCE = "FRED (Réserve fédérale de Saint-Louis), DGS10"


class FredRates(RateProvider):
    name = "fred"
    simulated = False

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    def overnight(self, series: str, start: date, end: date) -> PriceSeries:
        raise ProviderUnavailable("fred", "seul le taux long américain est servi par FRED")

    def long_yield(self, currency: str, start: date, end: date) -> PriceSeries:
        if currency != "USD":
            raise ProviderUnavailable("fred", f"pas de taux long FRED en {currency}")
        req = urllib.request.Request(URL.format(start=start.isoformat(), end=end.isoformat()),
                                     headers={"User-Agent": "Mozilla/5.0 (compatible; mini-terminal)"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                text = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raise ProviderUnavailable("fred", f"HTTP {e.code}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ProviderUnavailable("fred", str(e)) from e
        values = {}
        try:
            for r in csv.DictReader(io.StringIO(text)):
                v = r["DGS10"].strip()
                if v and v != ".":
                    values[pd.Timestamp(r["observation_date"])] = float(v)
        except (KeyError, ValueError) as e:
            raise ProviderUnavailable("fred", f"réponse illisible : {e}") from e
        return PriceSeries("USD10Y", clean_series(pd.Series(values, dtype=float)), SOURCE)
