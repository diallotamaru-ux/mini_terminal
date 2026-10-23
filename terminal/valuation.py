"""
Valorisation quotidienne d'un portefeuille réel et flux externes.

Grille quotidienne, week-ends compris (la crypto cote 7 j/7). Pour les
actions, le dernier cours connu est reporté au plus `MAX_STALE_DAYS` jours
(week-ends, jours fériés). Au-delà, la valeur est manquante (NaN), jamais nulle.
Un jour d'achat ou de vente sans cours de clôture prend le prix de la
transaction : c'est un prix observé.

Flux externes, en euros, positifs, par compte : règle unique
`ledger.external_flows` (dépôts et retraits pour un compte avec espèces ;
achats, ventes, dividendes et frais pour un compte en titres seuls).

Les opérations d'un compte « avec espèces » sont réglées en euros : au taux
du courtier s'il est fourni, sinon au taux de marché du jour.

Pour un compte « avec espèces », la poche titres (sans les espèces) est aussi
suivie, avec les flux de la convention « titres seuls ». Les deux conventions
donnent donc le même TWR des titres sur un même historique.

Les séries sont en flottants : elles alimentent des calculs statistiques.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from .ledger import Account, CashMode, Transaction, TxType, external_flows, ordered

MAX_STALE_DAYS = 7

COLUMNS = ["securities", "cash", "value", "inflow", "outflow", "sleeve_inflow", "sleeve_outflow"]


@dataclass
class History:
    accounts: dict[int, pd.DataFrame]        # colonnes COLUMNS, index quotidien
    total: pd.DataFrame                      # value, inflow, outflow, securities, cash
    holdings_eur: pd.DataFrame               # valeur EUR par (compte, ticker)
    prices: pd.DataFrame                     # cours utilisés, devise de cotation
    stale: pd.DataFrame                      # True si cours reporté ou issu d'une transaction
    warnings: list[str] = field(default_factory=list)


def _daily(series: pd.Series | None, grid: pd.DatetimeIndex) -> tuple[pd.Series, pd.Series]:
    """Reporte une série sur la grille. Renvoie (valeurs, masque « cours non frais »)."""
    if series is None or series.empty:
        nan = pd.Series(np.nan, index=grid)
        return nan, pd.Series(False, index=grid)
    s = series[~series.index.duplicated(keep="last")].sort_index()
    observed = s.reindex(grid)
    filled = s.reindex(grid.union(s.index)).ffill(limit=MAX_STALE_DAYS).reindex(grid)
    return filled, observed.isna() & filled.notna()


def build_history(accounts: list[Account], transactions: list[Transaction],
                  prices: dict[str, pd.Series], fx: dict[str, pd.Series],
                  end: date, start: date | None = None) -> History:
    """
    `prices[ticker]` : clôtures dans la devise de la cotation.
    `fx[devise]`     : euros pour une unité de devise (EUR n'est pas requis).
    Les transactions doivent avoir été validées par `ledger.validate`.
    """
    txs = ordered(transactions)
    warnings: list[str] = []
    if not txs:
        grid = pd.date_range(start or end, end, freq="D")
        empty = pd.DataFrame(0.0, index=grid, columns=COLUMNS)
        return History({a.id: empty.copy() for a in accounts}, empty[["securities", "cash", "value",
                       "inflow", "outflow"]].copy(), pd.DataFrame(index=grid),
                       pd.DataFrame(index=grid), pd.DataFrame(index=grid), ["Aucune transaction."])
    grid = pd.date_range(start or txs[0].date, end, freq="D")
    modes = {a.id: a.cash_mode for a in accounts}

    # Devise de chaque ticker, prise sur ses transactions (validées cohérentes).
    ticker_cur = {tx.ticker: tx.currency for tx in txs if tx.ticker}

    # --- Taux de change -----------------------------------------------------
    currencies = {tx.currency for tx in txs} | set(ticker_cur.values())
    fx_daily = {"EUR": pd.Series(1.0, index=grid)}
    for c in sorted(currencies - {"EUR"}):
        s, _ = _daily(fx.get(c), grid)
        if s.isna().all():
            warnings.append(f"Taux de change {c}/EUR indisponible : montants en {c} non convertis.")
        fx_daily[c] = s

    def rate_on(tx: Transaction) -> float:
        if tx.currency == "EUR":
            return 1.0
        if tx.fx_rate is not None:
            return float(tx.fx_rate)
        return float(fx_daily[tx.currency].get(pd.Timestamp(tx.date), np.nan))

    # --- Cours --------------------------------------------------------------
    px_cols, stale_cols = {}, {}
    for t in sorted(ticker_cur):
        base = prices.get(t)
        base = base.copy() if base is not None else pd.Series(dtype=float)
        for tx in txs:
            if tx.ticker == t and tx.type in (TxType.ACHAT, TxType.VENTE):
                d = pd.Timestamp(tx.date)
                if d not in base.index:
                    base.loc[d] = float(tx.price)
        if prices.get(t) is None or prices[t].empty:
            warnings.append(f"Aucun cours pour {t} : seuls les prix des transactions sont utilisés.")
        s, stale = _daily(base.sort_index(), grid)
        observed = prices.get(t)
        obs_idx = observed.index if observed is not None else pd.DatetimeIndex([])
        from_tx = pd.Series(grid.isin(base.index) & ~grid.isin(obs_idx), index=grid)
        px_cols[t], stale_cols[t] = s, stale | from_tx
    px = pd.DataFrame(px_cols, index=grid)
    stale = pd.DataFrame(stale_cols, index=grid)

    # --- Quantités, flux, espèces -------------------------------------------
    qty_delta: dict[tuple[int, str], dict] = {}
    rows = {a.id: {c: {} for c in ("cash", "inflow", "outflow", "sleeve_inflow", "sleeve_outflow")}
            for a in accounts}

    def bump(acc: int, col: str, d: date, v: float) -> None:
        bucket = rows[acc][col]
        key = pd.Timestamp(d)
        bucket[key] = bucket.get(key, 0.0) + v

    for tx in txs:
        if tx.date > end:
            continue
        acc, mode, d = tx.account_id, modes[tx.account_id], tx.date
        rate = rate_on(tx)
        if tx.type in (TxType.ACHAT, TxType.VENTE):
            sign = 1 if tx.type is TxType.ACHAT else -1
            k = (acc, tx.ticker)
            qty_delta.setdefault(k, {})
            qty_delta[k][pd.Timestamp(d)] = qty_delta[k].get(pd.Timestamp(d), 0.0) + sign * float(tx.quantity)
        if mode is CashMode.AVEC_ESPECES:
            bump(acc, "cash", d, float(tx.net_cash) * rate)
        flows = external_flows(tx, mode)
        for col in ("inflow", "outflow", "sleeve_inflow", "sleeve_outflow"):
            v = getattr(flows, col)
            if v:
                bump(acc, col, d, float(v) * rate)

    holdings = {}
    for (acc, t), deltas in sorted(qty_delta.items()):
        q = pd.Series(deltas).sort_index().cumsum().reindex(grid, method="ffill").fillna(0.0)
        q[q.abs() < 1e-12] = 0.0
        val = q * px[t] * fx_daily[ticker_cur[t]]
        val[q == 0.0] = 0.0              # position soldée : 0 exact, même sans cours
        holdings[(acc, t)] = val
        gaps = (q != 0.0) & val.isna()
        if gaps.any():
            first = grid[gaps.to_numpy()][0].date().isoformat()
            warnings.append(f"Valorisation manquante pour {t} ({int(gaps.sum())} jours, "
                            f"à partir du {first}).")
    holdings_eur = pd.DataFrame(holdings, index=grid)
    if not holdings_eur.empty:
        holdings_eur.columns = pd.MultiIndex.from_tuples(holdings_eur.columns, names=["account", "ticker"])

    frames = {}
    for a in accounts:
        f = pd.DataFrame(index=grid)
        cols = [c for c in holdings if c[0] == a.id]
        f["securities"] = (pd.concat([holdings[c] for c in cols], axis=1).sum(axis=1, skipna=False)
                           if cols else 0.0)
        for col, data in rows[a.id].items():
            f[col] = pd.Series(data, dtype=float).reindex(grid, fill_value=0.0) if data else 0.0
        # skipna=False : un taux manquant rend le solde inconnu, pas ignoré.
        f["cash"] = f["cash"].cumsum(skipna=False)
        f["value"] = f["securities"] + f["cash"]
        neg = f["cash"] < -0.005
        if a.cash_mode is CashMode.AVEC_ESPECES and neg.any():
            first = grid[neg.to_numpy()][0].date().isoformat()
            warnings.append(f"Compte {a.name} : solde d'espèces négatif à partir du {first}. "
                            f"Un dépôt manque probablement.")
        frames[a.id] = f[COLUMNS]

    if frames:
        total = sum(f[["securities", "cash", "value", "inflow", "outflow"]] for f in frames.values())
    else:  # pragma: no cover - aucun compte
        total = pd.DataFrame(0.0, index=grid, columns=["securities", "cash", "value", "inflow", "outflow"])
    return History(frames, total, holdings_eur, px, stale, warnings)
