"""
Graphiques Plotly partagés par le tableau de bord Streamlit et le rapport HTML.

Règles appliquées :
- Couleurs catégorielles attribuées dans un ordre fixe, par actif (jamais par rang).
- Portefeuille en encre principale, indice de référence en pointillés gris :
  ils ne consomment pas de couleur catégorielle.
- Un seul axe des ordonnées par graphique.
- Corrélations : palette divergente bleu <-> rouge, point milieu gris.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

THEMES = {
    "dark": {
        "surface": "#1a1a19", "page": "#0d0d0d",
        "ink": "#f0efec", "ink2": "#c3c2b7", "muted": "#898781",
        "grid": "#2c2c2a", "axis": "#383835",
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500",
                   "#d55181", "#008300", "#9085e9", "#e66767"],
        "div_mid": "#383835",
        "seq": ["#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4"],
    },
    "light": {
        "surface": "#fcfcfb", "page": "#f9f9f7",
        "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
        "grid": "#e1e0d9", "axis": "#c3c2b7",
        "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
                   "#e87ba4", "#008300", "#6250d6", "#e34948"],
        "div_mid": "#f0efec",
        "seq": ["#1c5cab", "#256abf", "#2a78d6", "#5598e7", "#86b6ef"],
    },
}
DIV_BLUE, DIV_RED = "#2a78d6", "#e34948"
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def color_map(assets: list[str], theme: str) -> dict[str, str]:
    """Couleur stable par actif : l'ordre de saisie fixe la couleur."""
    pal = THEMES[theme]["series"]
    return {a: pal[i % len(pal)] for i, a in enumerate(assets)}


def _layout(fig: go.Figure, theme: str, title: str, height: int = 380,
            yfmt: str | None = None, ytitle: str | None = None) -> go.Figure:
    t = THEMES[theme]
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=t["ink"]), x=0, xanchor="left"),
        paper_bgcolor=t["surface"], plot_bgcolor=t["surface"],
        font=dict(family=FONT, color=t["ink2"], size=12),
        height=height, margin=dict(l=56, r=16, t=44, b=40),
        hovermode="x unified",
        hoverlabel=dict(bgcolor=t["surface"], font_color=t["ink"], bordercolor=t["axis"]),
        legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="left", x=0,
                    font=dict(color=t["ink2"]), bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(showgrid=False, linecolor=t["axis"], tickfont=dict(color=t["muted"]))
    fig.update_yaxes(gridcolor=t["grid"], gridwidth=1, zeroline=False,
                     linecolor=t["axis"], tickfont=dict(color=t["muted"]),
                     tickformat=yfmt, title=ytitle)
    return fig


def _special_line(name: str, theme: str) -> dict:
    t = THEMES[theme]
    if name == "Portefeuille":
        return dict(color=t["ink"], width=2.5)
    return dict(color=t["muted"], width=2, dash="dash")  # indice de référence


def performance_chart(wealth: pd.DataFrame, colors: dict, theme: str,
                      specials: tuple[str, ...], log_scale: bool = True) -> go.Figure:
    fig = go.Figure()
    for col in wealth.columns:
        line = _special_line(col, theme) if col in specials else dict(color=colors[col], width=1.6)
        fig.add_trace(go.Scatter(x=wealth.index, y=wealth[col], name=col, mode="lines",
                                 line=line, hovertemplate="%{y:.1f}"))
    _layout(fig, theme, "Performance cumulée (base 100)", height=420)
    if log_scale:
        lo, hi = float(np.nanmin(wealth.values)), float(np.nanmax(wealth.values))
        nice = [1, 2, 5, 10, 20, 25, 50, 100, 150, 200, 300, 500, 1000, 2000, 5000, 10000, 20000]
        ticks = [v for v in nice if lo * 0.9 <= v <= hi * 1.1]
        fig.update_yaxes(type="log", tickvals=ticks, ticktext=[f"{v:g}" for v in ticks],
                         minor=dict(showgrid=False))
    return fig


def drawdown_chart(dd: pd.DataFrame, theme: str, specials: tuple[str, ...]) -> go.Figure:
    t = THEMES[theme]
    fig = go.Figure()
    for col in dd.columns:
        line = _special_line(col, theme)
        fill = "tozeroy" if col == "Portefeuille" else None
        fig.add_trace(go.Scatter(x=dd.index, y=dd[col], name=col, mode="lines", line=line,
                                 fill=fill, fillcolor="rgba(227,73,72,0.18)",
                                 hovertemplate="%{y:.1%}"))
    _layout(fig, theme, "Drawdown : baisse depuis le plus haut", height=300, yfmt=".0%")
    fig.add_hline(y=0, line_color=t["axis"], line_width=1)
    return fig


def rolling_chart(df: pd.DataFrame, colors: dict, theme: str, specials: tuple[str, ...],
                  title: str, yfmt: str) -> go.Figure:
    fig = go.Figure()
    for col in df.columns:
        line = _special_line(col, theme) if col in specials else dict(color=colors[col], width=1.4)
        fig.add_trace(go.Scatter(x=df.index, y=df[col], name=col, mode="lines", line=line,
                                 hovertemplate="%{y:" + yfmt + "}"))
    return _layout(fig, theme, title, height=320, yfmt=yfmt)


def correlation_heatmap(corr: pd.DataFrame, theme: str) -> go.Figure:
    t = THEMES[theme]
    scale = [[0.0, DIV_BLUE], [0.5, t["div_mid"]], [1.0, DIV_RED]]
    z = corr.values
    text = np.vectorize(lambda v: f"{v:.2f}")(z)
    fig = go.Figure(go.Heatmap(
        z=z, x=corr.columns, y=corr.index, zmin=-1, zmax=1, colorscale=scale,
        text=text, texttemplate="%{text}", textfont=dict(color=t["ink"], size=11),
        hovertemplate="%{y} / %{x} : %{z:.2f}<extra></extra>", xgap=2, ygap=2,
        colorbar=dict(thickness=10, tickfont=dict(color=t["muted"]), outlinewidth=0),
    ))
    _layout(fig, theme, "Corrélations des rendements quotidiens", height=420)
    fig.update_layout(hovermode="closest")
    fig.update_yaxes(autorange="reversed", showgrid=False)
    return fig


def bar_chart(values: pd.Series, theme: str, title: str, yfmt: str = ".0%",
              color: str | None = None) -> go.Figure:
    t = THEMES[theme]
    fig = go.Figure(go.Bar(
        x=values.index, y=values.values, marker=dict(color=color or t["seq"][2],
                                                     line=dict(width=0)),
        text=[_fmt(v, yfmt) for v in values.values],
        textposition="outside", textfont=dict(color=t["ink2"]),
        hovertemplate="%{x} : %{y:" + yfmt + "}<extra></extra>",
    ))
    _layout(fig, theme, title, height=320, yfmt=yfmt)
    fig.update_layout(hovermode="closest", bargap=0.35)
    fig.update_traces(marker_cornerradius=4)
    return fig


def _fmt(v: float, yfmt: str) -> str:
    if yfmt.endswith("%"):
        return f"{v:.1%}"
    return f"{v:.2f}"
