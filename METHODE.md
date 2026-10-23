### Conventions

- **Rendements simples quotidiens** : $r_t = P_t / P_{t-1} - 1$, avec $P_t$ le cours de clôture ajusté des dividendes et divisions d'actions.
- **Annualisation** sur $A = 252$ séances. Le taux sans risque annuel $r_f$ est converti en taux quotidien $r_{f,d} = (1 + r_f)^{1/A} - 1$.
- **Calendriers** : seules les dates où tous les actifs cotent sont conservées. Le rendement du lundi d'une crypto inclut donc son week-end : le rendement total reste exact, mais la volatilité quotidienne de la crypto est légèrement lissée.
- **Portefeuille** : $r_{p,t} = \sum_i w_i\, r_{i,t}$, avec $w_i$ le poids de l'actif $i$. Cela suppose un rééquilibrage quotidien. Un portefeuille réel, non rééquilibré, voit ses poids dériver. Cette hypothèse ne sert qu'au portefeuille théorique (`legacy/`). Le portefeuille réel est calculé à partir des transactions : voir la section suivante.

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

### Portefeuille réel (à partir des transactions)

**Données.** Montants en `Decimal` dans la base et le grand livre. Les flottants ne servent qu'aux séries
statistiques (historique de valeur, rendements). Valorisation au cours de clôture **ajusté des divisions mais
pas des dividendes** : les dividendes sont saisis comme transactions, des cours ajustés les compteraient deux fois.

**Prix de revient.** Coût moyen pondéré, frais d'achat inclus (méthode du PMP) :
$\mathrm{PRU} = C / q$, avec $C$ le coût des titres détenus et $q$ la quantité. Une vente de $q_v$ titres au
prix $p_v$ avec des frais $f$ réalise $q_v p_v - f - \mathrm{PRU}\, q_v$ et laisse le PRU inchangé. En euros,
chaque opération est convertie au taux du courtier s'il est saisi, sinon au taux de marché du jour.

**Conventions de flux**, une par compte, jamais deux :

| Convention | Apports $I_t$ | Retraits $O_t$ | Valeur $V_t$ |
|---|---|---|---|
| avec espèces | dépôts | retraits | titres + espèces |
| titres seuls | achats (brut + frais), frais | ventes (brut − frais), dividendes | titres |

Pour un compte avec espèces, la **poche titres** est aussi suivie avec la règle « titres seuls ». Sur un même
historique, les deux conventions donnent exactement le même TWR des titres (test
`test_securities_twr_identical_in_both_conventions`). Le TWR du compte avec espèces en diffère : les espèces
qui attendent diluent la performance. Le total du portefeuille somme valeurs et flux de tous les comptes.

**TWR** (rendement pondéré par le temps), sur une grille quotidienne qui inclut les week-ends :
$$r_t = \frac{V_t + O_t}{V_{t-1} + I_t} - 1, \qquad \mathrm{TWR} = \prod_t (1 + r_t) - 1.$$
Les apports arrivent en début de journée (ils travaillent au prix d'exécution réel), les retraits partent en fin
de journée. Tout en fin de journée donnerait un dénominateur nul le premier jour ; tout en début de journée
donnerait un dénominateur négatif quand on vend tout après une hausse. Entre deux flux, le produit se télescope :
la grille quotidienne donne exactement le TWR par sous-périodes. Un jour sans capital investi est exclu et signalé.

**TRI** (MWR, rendement pondéré par les capitaux) : le taux $r$ tel que
$\sum_k CF_k / (1 + r)^{(t_k - t_0)/365} = 0$. Flux du point de vue de l'investisseur : $-I_t$ daté du jour $t$,
$+O_t$ daté de $t + 1$, et la valeur finale comme dernier flux, datée du lendemain de la dernière clôture. La
racine est trouvée par la méthode de Brent, sur un intervalle élargi jusqu'à l'encadrer. Des flux tous de même
signe, ou sans racine réelle, renvoient une erreur explicite. Plusieurs racines sont possibles quand les flux
changent plusieurs fois de signe : la première trouvée est renvoyée.

**Annualisation.** $(1 + R)^{365/j} - 1$ sur $j$ jours calendaires, **seulement si $j \ge 365$** (convention
GIPS). En deçà, le rendement est affiché sur la période. Les indicateurs de risque des sections précédentes
restent en base 252 séances.

**Données manquantes.** Un cours est reporté au plus 7 jours (week-ends, jours fériés). Au-delà, la valeur est
manquante, jamais nulle : le total est marqué incomplet et le TWR n'est pas calculé. Un jour de transaction sans
clôture prend le prix de la transaction, marqué comme tel.

### Limites

- Toutes ces mesures sont des **estimations sur le passé**. Pour des rendements i.i.d., l'erreur-type du Sharpe estimé sur $n$ périodes vaut $\sqrt{(1 + S_p^2/2)/n}$, avec $S_p$ le Sharpe par période (Lo, 2002). En données quotidiennes, $S_p$ est petit et l'erreur-type du Sharpe annualisé se réduit à environ $1/\sqrt{T}$, avec $T$ la durée en années. Sur 5 ans : environ 0,45. Un Sharpe estimé de 0,8 a donc un intervalle de confiance à 95 % d'environ $0{,}8 \pm 1{,}96 \times 0{,}45$, soit $[-0{,}1\ ;\ 1{,}7]$.
- La VaR historique ne prévoit pas les crises absentes de l'échantillon.
- Les données Yahoo Finance sont gratuites et non garanties : erreurs ponctuelles possibles.

### Sources

- Sharpe, W. F. (1994). *The Sharpe Ratio*. Journal of Portfolio Management.
- Lo, A. W. (2002). *The Statistics of Sharpe Ratios*. Financial Analysts Journal.
- Meucci, A. (2009). *Managing Diversification*. Risk.
- Meucci, A., Santangelo, A., Deguest, R. (2015). *Risk Budgeting and Diversification Based on Optimized Uncorrelated Factors*. Risk.
