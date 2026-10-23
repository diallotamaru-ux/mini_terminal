# Mini-terminal

Tableau de bord d'analyse de portefeuille en Python : performance, risque, et diversification réelle.
Données gratuites via Yahoo Finance (`yfinance`).

## Installation

```bash
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -r requirements.txt
```

## Utilisation

```bash
streamlit run app.py               # tableau de bord interactif (navigateur)
python report.py                   # rapport HTML autonome : rapport.html
python report.py --theme light     # version fond clair, pour un article de blog
python report.py --demo            # données simulées, sans connexion
python -m pytest -q                # 18 tests sur cas analytiques connus
```

Modifiez `config.py` pour vos actifs, vos poids et votre indice de référence.

## Architecture

```
mini_terminal/
├── app.py              Tableau de bord Streamlit (interface seule, aucun calcul)
├── report.py           Rapport HTML statique, publiable sur un site
├── config.py           Paramètres par défaut
├── METHODE.md          Formules, conventions, limites, sources
├── terminal/
│   ├── data.py         Téléchargement, cache, devises, alignement des calendriers, mode démo
│   ├── metrics.py      Indicateurs : fonctions pures, sans réseau
│   ├── engine.py       Orchestration : Config -> Results
│   ├── charts.py       Graphiques Plotly (thèmes sombre et clair)
│   └── views.py        Assemblage des graphiques et mise en forme des tables
└── tests/
    └── test_metrics.py
```

Principe : les calculs (`metrics.py`) ne connaissent ni le réseau ni l'interface.
On peut donc les tester isolément et réutiliser le moteur dans un autre contexte.

## Indicateurs

Rendement total, CAGR, volatilité, Sharpe, Sortino, max drawdown, Calmar, VaR et CVaR historiques,
bêta, alpha de Jensen, tracking error, ratio d'information, contributions au risque (Euler),
nombre effectif de paris (ACP et torsion minimale). Détails et formules dans `METHODE.md`.

## Publier sur mathascience.com

Streamlit exige un serveur Python : un site WordPress ne peut pas l'exécuter. Deux options :

1. **Rapport statique.** `python report.py --theme light`, puis intégrer `rapport.html`
   (bloc HTML personnalisé ou iframe). Les graphiques restent interactifs.
2. **Application en ligne.** Pousser le dépôt sur GitHub, le déployer gratuitement sur
   Streamlit Community Cloud, et mettre le lien dans l'article.

## Pièges connus

- **Devises.** Sans conversion, un ETF en euros et une action en dollars sont mesurés chacun
  dans sa devise. Pour un investisseur en euros, choisir `EUR` dans la devise de calcul.
- **Calendriers.** La crypto cote 7 j/7. Seules les dates communes sont gardées : le rendement
  du lundi inclut le week-end.
- **Rééquilibrage.** Le portefeuille est supposé rééquilibré chaque jour à poids constants.
- **Petits échantillons.** Sur 5 ans de données quotidiennes, l'erreur-type d'un Sharpe annualisé
  vaut environ 0,45. Ne pas sur-interpréter un écart de 0,2.
