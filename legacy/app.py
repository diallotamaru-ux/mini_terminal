"""
Mini-terminal financier — tableau de bord Streamlit.

Lancement :  streamlit run legacy/app.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # racine du projet

from config import DEFAULT
from terminal import engine, views

st.set_page_config(page_title="Mini-terminal", layout="wide")

st.markdown("""
<style>
  .block-container {padding-top: 1.6rem; max-width: 1400px;}
  [data-testid="stMetricValue"] {font-variant-numeric: tabular-nums;}
  .note {color: #898781; font-size: 0.85rem;}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Paramètres
# ---------------------------------------------------------------------------

def parse_list(text: str) -> list[str]:
    return [t.strip().upper() for t in text.replace(";", ",").split(",") if t.strip()]


with st.sidebar:
    st.header("Paramètres")
    demo = st.toggle("Mode démo (données simulées)", value=DEFAULT["demo"],
                     help="Fonctionne hors ligne. Les chiffres sont fictifs.")
    assets_txt = st.text_area("Actifs (tickers Yahoo, séparés par des virgules)",
                              ", ".join(DEFAULT["assets"]), height=90)
    assets = parse_list(assets_txt)
    benchmark = st.text_input("Indice de référence", DEFAULT["benchmark"]).strip().upper()

    c1, c2 = st.columns(2)
    start = c1.date_input("Début", pd.Timestamp(DEFAULT["start"]).date(),
                          min_value=date(2000, 1, 1))
    end = c2.date_input("Fin", date.today())
    rf = st.number_input("Taux sans risque annuel (%)", 0.0, 15.0,
                         float(DEFAULT["rf_annual"] * 100), 0.25) / 100
    base_ccy = st.selectbox("Devise de calcul", ["Aucune conversion", "EUR", "USD"],
                            index=["Aucune conversion", "EUR", "USD"].index(DEFAULT["base_currency"] or "Aucune conversion"))
    window = st.slider("Fenêtre du Sharpe glissant (jours)", 63, 504,
                       DEFAULT["rolling_window"], 21)
    log_scale = st.toggle("Échelle logarithmique", value=True)

    st.subheader("Poids du portefeuille")
    st.caption("Normalisés automatiquement. Rééquilibrage quotidien supposé.")
    default_w = DEFAULT.get("weights") or {}
    weights = {}
    for a in assets:
        weights[a] = st.number_input(a, 0.0, 100.0,
                                     float(default_w.get(a, 100 / max(len(assets), 1))),
                                     1.0, key=f"w_{a}")

if not assets:
    st.info("Saisissez au moins un ticker.")
    st.stop()


@st.cache_data(show_spinner="Téléchargement et calcul...", ttl=3600)
def compute(assets, benchmark, weights, start, end, rf, ccy, demo, window):
    cfg = engine.Config(assets=list(assets), benchmark=benchmark, weights=dict(weights),
                        start=str(start), end=str(end), rf_annual=rf,
                        base_currency=None if ccy == "Aucune conversion" else ccy,
                        demo=demo, rolling_window=window)
    return engine.run(cfg)


try:
    res = compute(tuple(assets), benchmark, tuple(weights.items()), start, end, rf,
                  base_ccy, demo, window)
except Exception as exc:  # erreur réseau, ticker inconnu, etc.
    st.error(f"Calcul impossible : {exc}")
    st.stop()

figs = views.build_figures(res, theme="dark", log_scale=log_scale)
row_p = res.table.loc["Portefeuille"]
bname = res.bench.name
row_b = res.table.loc[bname]

# ---------------------------------------------------------------------------
# En-tête
# ---------------------------------------------------------------------------

st.title("Mini-terminal")
p0, p1 = res.prices.index[0].date(), res.prices.index[-1].date()
st.markdown(f"<span class='note'>{len(res.prices)} séances, du {p0} au {p1}. "
            f"Référence : {benchmark}. Taux sans risque : {rf:.2%}.</span>",
            unsafe_allow_html=True)
for w in res.warnings:
    st.warning(w)

k = st.columns(6)
k[0].metric("CAGR", f"{row_p['CAGR']:.1%}", f"{row_p['CAGR'] - row_b['CAGR']:+.1%} vs réf.")
k[1].metric("Volatilité", f"{row_p['Volatilité']:.1%}",
            f"{row_p['Volatilité'] - row_b['Volatilité']:+.1%} vs réf.", delta_color="inverse")
k[2].metric("Sharpe", f"{row_p['Sharpe']:.2f}", f"{row_p['Sharpe'] - row_b['Sharpe']:+.2f} vs réf.")
k[3].metric("Max drawdown", f"{row_p['Max drawdown']:.1%}",
            f"{row_p['Max drawdown'] - row_b['Max drawdown']:+.1%} vs réf.")
ir = row_p["Ratio d'information"]
k[4].metric("Ratio d'information", f"{ir:.2f}")
k[5].metric("ENB (ACP)", f"{res.pca['enb']:.2f}",
            f"torsion {res.mt['enb']:.2f} · {res.pca['n_assets']} lignes",
            delta_color="off", delta_arrow="off",
            help="Nombre effectif de paris indépendants. Voir l'onglet Diversification.")

# ---------------------------------------------------------------------------
# Onglets
# ---------------------------------------------------------------------------

t_perf, t_risk, t_div, t_table, t_method = st.tabs(
    ["Performance", "Risque", "Diversification", "Tableau", "Méthode"])

with t_perf:
    st.plotly_chart(figs["performance"], width="stretch")
    st.plotly_chart(figs["rolling_sharpe"], width="stretch")

with t_risk:
    st.plotly_chart(figs["drawdown"], width="stretch")
    st.plotly_chart(figs["rolling_vol"], width="stretch")

with t_div:
    a, b = st.columns(2)
    a.plotly_chart(figs["corr"], width="stretch")
    b.plotly_chart(figs["risk_contrib"], width="stretch")
    a, b = st.columns(2)
    a.plotly_chart(figs["pca"], width="stretch")
    b.plotly_chart(figs["mt"], width="stretch")
    pc1 = res.pca["portfolio_variance_share"].iloc[0]
    st.markdown(
        f"**Lecture.** Le premier facteur statistique porte {pc1:.0%} de la variance du "
        f"portefeuille. ENB par ACP : {res.pca['enb']:.2f} paris effectifs. ENB par torsion "
        f"minimale : {res.mt['enb']:.2f}. Un écart important entre les deux signale un "
        "facteur commun que la torsion, symétrique par construction, ne voit pas.")

with t_table:
    st.dataframe(views.format_table(res.table), width="stretch")
    st.download_button("Exporter en CSV", res.table.to_csv().encode("utf-8"),
                       "indicateurs.csv", "text/csv")
    st.caption("VaR et CVaR : pertes quotidiennes historiques, au seuil de 95 %.")

with t_method:
    st.markdown((Path(__file__).resolve().parent.parent / "METHODE.md").read_text(encoding="utf-8"))
