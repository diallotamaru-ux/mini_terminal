"""Références dividendes réinvestis converties en euros, calculées à la main."""

import numpy as np
import pandas as pd
import pytest

from terminal.benchmark import to_eur, total_return_index

IDX = pd.DatetimeIndex(["2025-03-20", "2025-03-21", "2025-03-24"])      # jeu., ven., lun.


def test_total_return_with_net_dividend_hand_example():
    # Cours 100, 99, 101 $ ; dividende brut 1 $ à l'ex-date du 21/03 ; retenue 15 %.
    # I_0 = 1
    # I_1 = 1 x (99 + 1 x 0,85) / 100 = 0,9985
    # I_2 = 0,9985 x 101 / 99 = 1,018671...
    p = pd.Series([100.0, 99.0, 101.0], index=IDX)
    d = pd.Series([1.0], index=[pd.Timestamp("2025-03-21")])
    i = total_return_index(p, d, withholding=0.15)
    assert i.tolist() == pytest.approx([1.0, 0.9985, 0.9985 * 101 / 99])
    # Brut (retenue nulle) : I_1 = (99 + 1) / 100 = 1.
    assert total_return_index(p, d).iloc[1] == pytest.approx(1.0)
    # Sans dividende : indice = prix / premier prix.
    assert total_return_index(p, base=100).tolist() == pytest.approx([100, 99, 101])


def test_dividend_on_non_trading_day_goes_to_next_session():
    # Ex-date un samedi (22/03) : rattachée à la séance du lundi 24/03.
    p = pd.Series([100.0, 100.0, 100.0], index=IDX)
    d = pd.Series([2.0], index=[pd.Timestamp("2025-03-22")])
    assert total_return_index(p, d).tolist() == pytest.approx([1.0, 1.0, 1.02])
    # Dividende antérieur à la série : ignoré.
    assert total_return_index(p, pd.Series([5.0], index=[pd.Timestamp("2020-01-01")])).iloc[-1] == 1.0


def test_conversion_to_eur_hand_example():
    # Indice 1 ; 0,9985 ; 1,018671 en USD. Taux USD→EUR : 0,92 jeu., 0,91 ven., week-end sans cotation,
    # 0,93 lun. Indice en EUR : 0,92 ; 0,9985 x 0,91 = 0,908635 ; 1,018671 x 0,93.
    p = pd.Series([100.0, 99.0, 101.0], index=IDX)
    d = pd.Series([1.0], index=[pd.Timestamp("2025-03-21")])
    usd = total_return_index(p, d, withholding=0.15)
    fx = pd.Series([0.92, 0.91, 0.93], index=IDX)
    eur = to_eur(usd, fx)
    assert eur.tolist() == pytest.approx([0.92, 0.9985 * 0.91, 0.9985 * 101 / 99 * 0.93])
    # Rendement en EUR du lundi = (1 + rendement en USD) x (1 + variation du change) - 1.
    r = eur.pct_change().iloc[-1]
    assert r == pytest.approx((101 / 99) * (0.93 / 0.91) - 1)


def test_fx_carried_then_missing():
    idx = pd.date_range("2025-01-01", periods=12, freq="D")
    s = pd.Series(1.0, index=idx)
    fx = pd.Series([0.9], index=[idx[0]])
    out = to_eur(s, fx)
    assert out.iloc[:8].tolist() == [0.9] * 8 and out.iloc[8:].isna().all()     # 7 jours de report au plus
    assert to_eur(s, None).equals(s)
    assert to_eur(s, pd.Series(dtype=float)).isna().all()


def test_invalid_withholding_and_empty():
    with pytest.raises(ValueError):
        total_return_index(pd.Series([1.0]), withholding=1.0)
    assert total_return_index(pd.Series(dtype=float)).empty
