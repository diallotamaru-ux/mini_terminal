### Conventions

- **Rendements simples quotidiens** : $r_t = P_t / P_{t-1} - 1$, avec $P_t$ le cours de clôture ajusté des dividendes et divisions d'actions.
- **Annualisation** sur $A = 252$ séances. Le taux sans risque annuel $r_f$ est converti en taux quotidien $r_{f,d} = (1 + r_f)^{1/A} - 1$.
- **Calendriers** : seules les dates où tous les actifs cotent sont conservées. Le rendement du lundi d'une crypto inclut donc son week-end : le rendement total reste exact, mais la volatilité quotidienne de la crypto est légèrement lissée.
- **Portefeuille** : $r_{p,t} = \sum_i w_i\, r_{i,t}$, avec $w_i$ le poids de l'actif $i$. Cela suppose un rééquilibrage quotidien. Un portefeuille réel, non rééquilibré, voit ses poids dériver.

### Indicateurs

| Indicateur | Formule | Lecture |
|---|---|---|
| CAGR | $(1 + R)^{A/N} - 1$ | $R$ rendement total, $N$ nombre de séances. Croissance annuelle composée. |
| Volatilité | $\sigma_d \sqrt{A}$ | $\sigma_d$ écart-type des rendements quotidiens. |
| Sharpe | $\dfrac{\overline{r - r_{f,d}}}{\sigma(r - r_{f,d})}\sqrt{A}$ | Rendement excédentaire par unité de risque total. |
| Sortino | $\dfrac{A\,\overline{r - r_{f,d}}}{DD}$ | $DD$ écart-type des seules baisses sous $r_{f,d}$, annualisé. |
| Max drawdown | $\min_t \left( W_t / \max_{s \le t} W_s - 1 \right)$ | $W_t$ valeur du portefeuille. Pire perte depuis un plus haut. |
| Calmar | CAGR / \|MDD\| | Croissance par unité de pire perte. |
| Bêta | $\mathrm{Cov}(r_i, r_b) / \mathrm{Var}(r_b)$ | $r_b$ rendement de la référence. Sensibilité au marché. |
| Alpha de Jensen | $A\left[\overline{r_i - r_f} - \beta\,\overline{r_b - r_f}\right]$ | Rendement non expliqué par le bêta. |
| Tracking error | $\sigma(r_i - r_b)\sqrt{A}$ | Écart de trajectoire avec la référence. |
| Ratio d'information | $A\,\overline{r_i - r_b} \,/\, TE$ | Surperformance par unité d'écart à la référence. |
| VaR 95 % | $-q_{0,05}(r)$ | $q_{0,05}$ quantile à 5 %. Perte quotidienne dépassée 1 jour sur 20. |
| CVaR 95 % | $-\mathbb{E}[r \mid r \le q_{0,05}]$ | Perte moyenne les jours au-delà de la VaR. |

### Diversification

**Contribution au risque (Euler)** : $RC_i = w_i (\Sigma w)_i \,/\, w^\top \Sigma w$, avec $\Sigma$ la matrice de covariance. La somme des $RC_i$ vaut 1. Une ligne à 10 % du capital peut porter 30 % du risque.

**Nombre effectif de paris (ENB)** : $\mathrm{ENB} = \exp\left(-\sum_k p_k \ln p_k\right)$, avec $p_k$ la part de variance portée par le facteur $k$. Il vaut 1 si un seul facteur porte tout le risque, $N$ si $N$ facteurs se le partagent également. Deux définitions des facteurs coexistent :

- **ACP** (Meucci, 2009) : facteurs = composantes principales de $\Sigma$. Détecte un facteur commun. Instable quand les valeurs propres sont proches, c'est-à-dire quand le portefeuille est déjà diversifié.
- **Torsion minimale** (Meucci, Santangelo, Deguest, 2015) : facteurs décorrélés les plus proches possible des actifs. Stable, et lisible ligne par ligne. Symétrique par construction : aveugle à un facteur commun quand les poids sont égaux.

Les deux se lisent ensemble. ACP basse et torsion haute : un facteur commun domine.

### Limites

- Toutes ces mesures sont des **estimations sur le passé**. Pour des rendements i.i.d., l'erreur-type du Sharpe estimé sur $n$ périodes vaut $\sqrt{(1 + S_p^2/2)/n}$, avec $S_p$ le Sharpe par période (Lo, 2002). En données quotidiennes, $S_p$ est petit et l'erreur-type du Sharpe annualisé se réduit à environ $1/\sqrt{T}$, avec $T$ la durée en années. Sur 5 ans : environ 0,45. Un Sharpe estimé de 0,8 a donc un intervalle de confiance à 95 % d'environ $0{,}8 \pm 1{,}96 \times 0{,}45$, soit $[-0{,}1\ ;\ 1{,}7]$.
- La VaR historique ne prévoit pas les crises absentes de l'échantillon.
- Les données Yahoo Finance sont gratuites et non garanties : erreurs ponctuelles possibles.

### Sources

- Sharpe, W. F. (1994). *The Sharpe Ratio*. Journal of Portfolio Management.
- Lo, A. W. (2002). *The Statistics of Sharpe Ratios*. Financial Analysts Journal.
- Meucci, A. (2009). *Managing Diversification*. Risk.
- Meucci, A., Santangelo, A., Deguest, R. (2015). *Risk Budgeting and Diversification Based on Optimized Uncorrelated Factors*. Risk.
