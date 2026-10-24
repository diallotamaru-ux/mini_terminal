"""DCF inversé : cas à réponse connue, calculés à la main."""

import numpy as np
import pandas as pd
import pytest

from terminal import dcf
from terminal.dcf import Assumptions, DCFError, Missing
from terminal.marketdata.base import fundamentals_frame


def table(**years):
    """table(y2025={...}, y2024={...}) -> tableau des comptes, champs absents = NaN."""
    rows = {}
    for y, values in years.items():
        for f, v in values.items():
            rows.setdefault(f, {})[pd.Timestamp(f"{y[1:]}-12-31")] = v
    return fundamentals_frame({f: pd.Series(v, dtype=float) for f, v in rows.items()})


# Exemple complet : t = 200 / 800 = 25 %.
FULL = dict(ocf=1000.0, capex=-200.0, interest_expense=50.0, pretax_income=800.0, tax_provision=200.0, sbc=30.0,
            financial_debt=500.0, lease_liabilities=100.0, cash_sti=300.0, lt_investments=0.0, minority_interest=20.0, diluted_shares=10.0,
            revenue=5000.0)


# ---------------------------------------------------------------------------
# Équation et résolution
# ---------------------------------------------------------------------------

def test_dcf_value_by_hand_one_year():
    # N = 1, g = 5 %, k = 10 %, g_term = 2 % : 105 / 1,1 + 105 × 1,02 / (0,08 × 1,1) = 95,4545… + 1 217,0454… = 1 312,5
    assert dcf.dcf_value(100.0, 0.05, 0.10, 1, 0.02) == pytest.approx(1312.5, abs=1e-9)
    assert dcf.implied_growth(100.0, 1312.5, 0.10, 1, 0.02) == pytest.approx(0.05, abs=1e-12)


def test_implied_growth_recovers_known_g():
    # VE construite à partir de g = 7 % : le solveur doit retrouver 7 %.
    ev = dcf.dcf_value(100.0, 0.07, 0.09, 10, 0.02)
    explicit = sum(100 * 1.07 ** t / 1.09 ** t for t in range(1, 11))
    terminal = 100 * 1.07 ** 10 * 1.02 / (0.07 * 1.09 ** 10)
    assert ev == pytest.approx(explicit + terminal, rel=1e-14)
    assert dcf.implied_growth(100.0, ev, 0.09, 10, 0.02) == pytest.approx(0.07, abs=1e-10)
    for g in (-0.30, 0.0, 0.25, 0.9):
        assert dcf.implied_growth(50.0, dcf.dcf_value(50.0, g, 0.08, 7, 0.015), 0.08, 7, 0.015) == \
            pytest.approx(g, abs=1e-10)


def test_value_increases_with_g():
    v = [dcf.dcf_value(100.0, g, 0.09, 10, 0.02) for g in np.linspace(-0.5, 1.0, 31)]
    assert all(b > a for a, b in zip(v, v[1:]))


def test_k_not_above_g_term_is_refused():
    for k in (0.02, 0.015):
        with pytest.raises(DCFError) as e:
            dcf.implied_growth(100.0, 2000.0, k, 10, 0.02)
        assert e.value.code == "k_le_gterm" and "strictement supérieur" in str(e.value)
    with pytest.raises(DCFError):
        dcf.dcf_value(100.0, 0.05, 0.02, 10, 0.02)


def test_negative_or_zero_fcf_is_refused():
    for f0 in (-10.0, 0.0):
        with pytest.raises(DCFError) as e:
            dcf.implied_growth(f0, 1000.0, 0.09, 10, 0.02)
        assert e.value.code == "fcf_negatif" and "pas de DCF inversé" in str(e.value)


def test_other_refusals():
    with pytest.raises(DCFError) as e:
        dcf.implied_growth(100.0, -5.0, 0.09, 10, 0.02)
    assert e.value.code == "ve_negative"
    with pytest.raises(DCFError) as e:                     # VE minuscule : il faudrait < −99 %/an
        dcf.implied_growth(100.0, 0.5, 0.09, 10, 0.02)       # V(−99 %) ≈ 0,92
    assert e.value.code == "sans_solution"
    with pytest.raises(DCFError) as e:                     # VE gigantesque : il faudrait > 200 %/an
        dcf.implied_growth(100.0, 1e15, 0.09, 10, 0.02)
    assert e.value.code == "sans_solution"
    for n in (0, 2.5):
        with pytest.raises(DCFError):
            dcf.implied_growth(100.0, 1000.0, 0.09, n, 0.02)
    with pytest.raises(DCFError):
        dcf.implied_growth(100.0, 1000.0, -1.5, 10, -2.0)


# ---------------------------------------------------------------------------
# Sensibilité
# ---------------------------------------------------------------------------

def test_sensitivity_is_monotone():
    ev = dcf.dcf_value(100.0, 0.08, 0.09, 10, 0.02)
    grid = dcf.sensitivity(100.0, ev, 0.09, 10)
    assert len(grid) == 5 and all(len(r) == 5 for r in grid)
    assert grid[2][2].g == pytest.approx(0.08, abs=1e-10)          # case centrale = hypothèses de base
    for r in grid:                                                  # g décroît quand g_term augmente
        gs = [c.g for c in r]
        assert all(b < a for a, b in zip(gs, gs[1:]))
    for j in range(5):                                              # g croît avec k
        gs = [grid[i][j].g for i in range(5)]
        assert all(b > a for a, b in zip(gs, gs[1:]))


def test_sensitivity_marks_impossible_cells():
    grid = dcf.sensitivity(100.0, 5000.0, 0.03, 10)                 # k de 1 % à 5 %
    first = grid[0]                                                 # k = 1 % : g_term ≥ 1 % impossible
    assert all(c.g is None and c.reason == "k ≤ g terminal" for c in first)
    assert grid[4][0].g is not None and grid[4][0].reason is None


# ---------------------------------------------------------------------------
# FCFF et valeur d'entreprise : cohérence
# ---------------------------------------------------------------------------

def test_fcff_by_hand_ifrs_operating_interest():
    r = dcf.fcff(table(y2025=FULL), Assumptions(k=0.09, fcf_years=1))
    # 1 000 − 200 + 50 × (1 − 0,25) − 30 = 807,5
    assert r.tax_rate == pytest.approx(0.25) and r.fcff0 == pytest.approx(807.5)
    assert "intérêts × (1 − t)" in r.rule and "rémunération en actions" in r.rule and not r.warnings


def test_fcff_ifrs_financing_interest_not_added():
    r = dcf.fcff(table(y2025=FULL), Assumptions(k=0.09, fcf_years=1, interest_class="financement"))
    assert r.fcff0 == pytest.approx(770.0) and r.tax_rate is None and "financement" in r.rule


def test_fcff_us_gaap_always_adds_interest():
    a = Assumptions(k=0.09, fcf_years=1, standard="us_gaap", interest_class="financement")
    assert dcf.fcff(table(y2025=FULL), a).fcff0 == pytest.approx(807.5)


def test_fcff_without_sbc_deduction_and_statutory_tax():
    r = dcf.fcff(table(y2025=FULL), Assumptions(k=0.09, fcf_years=1, sbc_deduct=False, statutory_tax=0.30))
    assert r.fcff0 == pytest.approx(1000 - 200 + 50 * 0.7) and r.tax_source == "taux légal (saisi)"


def test_fcff_average_over_years():
    t = table(y2023={**FULL, "ocf": 800.0}, y2024={**FULL, "ocf": 900.0}, y2025=FULL)
    r = dcf.fcff(t, Assumptions(k=0.09, fcf_years=3))
    # FCFF : 607,5 ; 707,5 ; 807,5 ; t = 600 / 2 400 = 25 %
    assert r.fcff0 == pytest.approx(707.5) and r.tax_source == "effectif moyen 2023-2025"
    assert len(r.window) == 3
    with pytest.raises(DCFError) as e:
        dcf.fcff(t, Assumptions(k=0.09, fcf_years=4))
    assert e.value.code == "historique"
    with pytest.raises(DCFError):
        dcf.fcff(t, Assumptions(k=0.09, fcf_years=0))
    with pytest.raises(DCFError):
        dcf.fcff(t, Assumptions(k=0.09, standard="pcg"))


def test_enterprise_value_by_hand():
    t = table(y2025=FULL)
    ifrs = dcf.enterprise_value(t, price=100.0, fx=1.0, a=Assumptions(k=0.09))
    # 100 × 10 + 600 − 300 + 20 = 1 320 (IFRS : dettes locatives comprises)
    assert (ifrs.market_cap, ifrs.debt, ifrs.ev) == (1000.0, 600.0, 1320.0) and not ifrs.warnings
    us = dcf.enterprise_value(t, price=100.0, fx=1.0, a=Assumptions(k=0.09, standard="us_gaap"))
    assert (us.debt, us.ev) == (500.0, 1220.0) and "dettes locatives exclues" in us.debt_rule
    usd = dcf.enterprise_value(t, price=100.0, fx=0.5, a=Assumptions(k=0.09))   # cotation ≠ devise des comptes
    assert usd.market_cap == 500.0 and usd.ev == 820.0


def test_leases_needed_in_ifrs_only():
    t = table(y2025={**FULL, "lease_liabilities": np.nan})
    us = dcf.enterprise_value(t, 100.0, 1.0, Assumptions(k=0.09, standard="us_gaap"))
    assert us.debt == 500.0 and "exclues" in us.debt_rule and not us.warnings
    with pytest.raises(Missing) as e:
        dcf.enterprise_value(t, 100.0, 1.0, Assumptions(k=0.09, standard="ifrs"))
    assert [i.field for i in e.value.items] == ["lease_liabilities"] and "IFRS" in e.value.items[0].remedy


def test_fcff_and_ev_consistency_end_to_end():
    # Le g implicite se calcule sur FCFF et VE construits par le module, jamais sur FCF actionnaire / capitalisation.
    t = table(y2025=FULL)
    a = Assumptions(k=0.09, fcf_years=1)
    f, v = dcf.fcff(t, a), dcf.enterprise_value(t, 100.0, 1.0, a)
    g = dcf.implied_growth(f.fcff0, v.ev, a.k, a.horizon, a.g_term)
    assert dcf.dcf_value(807.5, g, 0.09, 10, 0.02) == pytest.approx(1320.0, rel=1e-12)


# ---------------------------------------------------------------------------
# Données manquantes : jamais remplacées par zéro
# ---------------------------------------------------------------------------

def test_missing_sbc_blocks():
    t = table(y2025={**FULL, "sbc": np.nan})
    with pytest.raises(Missing) as e:
        dcf.fcff(t, Assumptions(k=0.09, fcf_years=1))
    assert [i.field for i in e.value.items] == ["sbc"] and "2025-12-31" in e.value.items[0].label
    assert dcf.fcff(t, Assumptions(k=0.09, fcf_years=1, sbc_deduct=False)).fcff0 == pytest.approx(837.5)


def test_missing_interest_blocks_unless_approximation_accepted():
    t = table(y2024=FULL, y2025={**FULL, "interest_expense": np.nan})
    with pytest.raises(Missing) as e:
        dcf.fcff(t, Assumptions(k=0.09, fcf_years=2))
    assert [(i.fiscal_end.year, i.field) for i in e.value.items] == [(2025, "interest_expense")]
    assert "approximation" in e.value.items[0].remedy
    r = dcf.fcff(t, Assumptions(k=0.09, fcf_years=2, accept_interest_approx=True))
    assert r.fcff0 == pytest.approx(770.0) and r.tax_rate is None
    assert "g implicite est surestimé" in r.warnings[0] and "intérêts" not in r.rule


def test_missing_year_in_window_is_named():
    t = table(y2023=FULL, y2024={**FULL, "ocf": np.nan}, y2025=FULL)
    with pytest.raises(Missing) as e:
        dcf.fcff(t, Assumptions(k=0.09, fcf_years=3))
    assert [(i.fiscal_end.year, i.field) for i in e.value.items] == [(2024, "ocf")]
    assert "2024-12-31" in str(e.value)


def test_missing_tax_inputs_and_negative_pretax():
    with pytest.raises(Missing) as e:
        dcf.fcff(table(y2025={**FULL, "tax_provision": np.nan}), Assumptions(k=0.09, fcf_years=1))
    assert e.value.items[0].field == "tax_provision" and "taux légal" in e.value.items[0].remedy
    with pytest.raises(DCFError) as e:
        dcf.fcff(table(y2025={**FULL, "pretax_income": -10.0}), Assumptions(k=0.09, fcf_years=1))
    assert e.value.code == "impot"


def test_missing_balance_sheet_items():
    t = table(y2025={**FULL, "minority_interest": np.nan, "cash_sti": np.nan})
    with pytest.raises(Missing) as e:
        dcf.enterprise_value(t, 100.0, 1.0, Assumptions(k=0.09))
    assert {i.field for i in e.value.items} == {"cash_sti", "minority_interest"}
    t = table(y2025={**FULL, "minority_interest": np.nan})
    ev = dcf.enterprise_value(t, 100.0, 1.0, Assumptions(k=0.09, accept_minority_approx=True))
    assert ev.minority is None and ev.ev == 1300.0 and "minoritaires" in ev.warnings[0]
    with pytest.raises(DCFError):
        dcf.enterprise_value(table(y2025=FULL), float("nan"), 1.0, Assumptions(k=0.09))
    with pytest.raises(DCFError):
        dcf.enterprise_value(fundamentals_frame({}), 100.0, 1.0, Assumptions(k=0.09))


def test_history_keeps_missing_years_missing():
    t = table(y2024={**FULL, "sbc": np.nan}, y2025=FULL)
    r = dcf.fcff(t, Assumptions(k=0.09, fcf_years=1))
    assert pd.isna(r.table.loc["2024-12-31", "fcff"]) and r.table.loc["2025-12-31", "fcff"] == pytest.approx(807.5)


# ---------------------------------------------------------------------------
# Croissance historique, périmètre, coût du capital, phrase
# ---------------------------------------------------------------------------

def test_historical_growth():
    s = pd.Series([100.0, np.nan, 121.0], index=pd.to_datetime(["2023-12-31", "2024-12-31", "2025-12-31"]))
    g = dcf.historical_growth(s)
    assert g.status == "ok" and g.value == pytest.approx(0.10) and g.years == 2 and g.n_points == 2
    neg = dcf.historical_growth(pd.Series([-5.0, 10.0], index=pd.to_datetime(["2024-12-31", "2025-12-31"])))
    assert neg.status == "non_significatif" and neg.value is None and neg.years == 1
    end_neg = dcf.historical_growth(pd.Series([5.0, -1.0], index=pd.to_datetime(["2024-12-31", "2025-12-31"])))
    assert end_neg.status == "non_significatif"
    assert dcf.historical_growth(pd.Series([5.0], index=pd.to_datetime(["2025-12-31"]))).status == "manquant"
    same_year = dcf.historical_growth(pd.Series([5.0, 6.0], index=pd.to_datetime(["2025-01-31", "2025-06-30"])))
    assert same_year.status == "manquant"


@pytest.mark.parametrize("asset_class,quote_type,industry,override,excluded,word", [
    ("etf", "ETF", None, None, True, "Fonds"),
    ("action", "ETF", None, None, True, "Fonds"),
    ("crypto", "CRYPTOCURRENCY", None, None, True, "Cryptoactif"),
    ("autre", None, None, None, True, "actions"),
    ("action", "EQUITY", "Banks - Regional", None, True, "Banque"),
    ("action", "EQUITY", "Insurance - Life", None, True, "assurance"),
    ("action", "EQUITY", "Insurance Brokers", None, False, None),
    ("action", "EQUITY", "Luxury Goods", True, True, "Banque"),
    ("action", "EQUITY", "Banks - Diversified", False, False, None),
    ("action", "EQUITY", "Semiconductors", None, False, None),
])
def test_eligibility(asset_class, quote_type, industry, override, excluded, word):
    reason = dcf.eligibility(asset_class, quote_type, industry, override)
    assert (reason is not None) == excluded
    if word:
        assert word in reason


def test_capm_k_by_hand():
    # β = 1,3 -> Blume 1,201 ; ke = 3 % + 1,201 × 5 % = 9,005 % ; kd = 10 / 200 × 0,75 = 3,75 % ; E/V = 0,8
    c = dcf.capm_k(0.03, 0.05, 1.3, market_cap=800.0, debt=200.0, interest=10.0, avg_debt=200.0, tax=0.25)
    assert c.beta_adj == pytest.approx(1.201) and c.ke == pytest.approx(0.09005)
    assert c.kd_after_tax == pytest.approx(0.0375) and c.k == pytest.approx(0.8 * 0.09005 + 0.2 * 0.0375)
    assert dcf.capm_k(0.03, 0.05, 1.0, 800.0, 0.0, None, None, None).k == pytest.approx(0.08)   # sans dette
    missing = dcf.capm_k(0.03, 0.05, 1.0, 800.0, 200.0, None, 200.0, 0.25)
    assert missing.k is None and missing.ke == pytest.approx(0.08) and "dette" in missing.reason
    assert dcf.capm_k(0.03, 0.05, None, 800.0, 200.0, 10.0, 200.0, 0.25).reason.startswith("β")
    assert dcf.common_k(0.027, 0.05) == pytest.approx(0.077)


def test_sentence_is_neutral():
    s = dcf.sentence(0.0734, 10, 0.02, 0.09)
    assert s == ("Le prix actuel suppose une croissance du flux disponible de 7,3 % par an pendant 10 ans, puis de "
                 "2,0 % par an à perpétuité, avec un coût du capital de 9,0 %.")
    assert "−5,0 %" in dcf.sentence(-0.05, 10, 0.02, 0.09)
    for word in ("acheter", "vendre", "sous-évalu", "surévalu", "opportunit"):
        assert word not in s.lower()


def test_long_term_investments_subtracted_like_cash():
    """Placements non courants : retranchés de la VE ; manquants, ils restent manquants (pas 0) et sont signalés."""
    a = Assumptions(k=0.09, standard="us_gaap")
    base = dcf.enterprise_value(table(y2025={**FULL, "lt_investments": np.nan}), 100.0, 1.0, a)
    assert base.lt_investments is None and "non courants manquants" in base.warnings[-1]
    with_lt = dcf.enterprise_value(table(y2025={**FULL, "lt_investments": 70.0}), 100.0, 1.0, a)
    assert with_lt.lt_investments == 70.0 and with_lt.ev == base.ev - 70.0
    assert not any("non courants" in w for w in with_lt.warnings)
    zero = dcf.enterprise_value(table(y2025={**FULL, "lt_investments": 0.0}), 100.0, 1.0, a)
    assert zero.lt_investments == 0.0 and zero.ev == base.ev                   # 0 saisi : sans avertissement
    assert not any("non courants" in w for w in zero.warnings)

