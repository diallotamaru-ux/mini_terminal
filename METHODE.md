### Conventions

- **Rendements simples quotidiens** : $r_t = P_t / P_{t-1} - 1$, avec $P_t$ le cours de clôture ajusté des dividendes et divisions d'actions.
- **Annualisation** sur $A = 252$ séances pour une série de séances de bourse effectives (portefeuille théorique, `legacy/`). Le portefeuille réel est mesuré sur une grille de jours ouvrés du lundi au vendredi, fériés compris (rendement nul ces jours-là), soit $A = 261$ points par an ($365.25 \times 5/7$) : voir « Risque et comparaison ». Le taux sans risque annuel $r_f$ est converti en taux quotidien $r_{f,d} = (1 + r_f)^{1/A} - 1$.
- **Calendriers** : seules les dates où tous les actifs cotent sont conservées. Le rendement du lundi d'une crypto inclut donc son week-end : le rendement total reste exact, mais la volatilité quotidienne de la crypto est légèrement lissée.
- **Portefeuille** : $r_{p,t} = \sum_i w_i\, r_{i,t}$, avec $w_i$ le poids de l'actif $i$. Cela suppose un rééquilibrage quotidien. Un portefeuille réel, non rééquilibré, voit ses poids dériver. Cette hypothèse ne sert qu'au portefeuille théorique (`legacy/`). Le portefeuille réel est calculé à partir des transactions : voir la section suivante.

### Indicateurs

| Indicateur | Formule | Lecture |
|---|---|---|
| CAGR | $(1 + R)^{A/N} - 1$ | $R$ rendement total, $N$ nombre d'observations de la série. Croissance annuelle composée. |
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

**Divisions d'actions.** Les cours du fournisseur sont ajustés des divisions, pas les transactions saisies.
Chaque achat ou vente daté **strictement avant** la date d'effet d'une division de ratio $n/d$ (actions nouvelles
pour anciennes : 10/1 pour une division par 10, 1/8 pour un regroupement) est ajusté au calcul :
$q' = q\, n/d$, $p' = p\, d/n$, montant brut inchangé. Les divisions successives se cumulent. Le coût total, les frais,
la plus-value réalisée et la valeur sont donc inchangés ; seul le PRU est exprimé par action nouvelle. Les données
saisies ne sont jamais modifiées, et la liste des ajustements est affichée. La validation (ventes à découvert) se
fait sur les quantités ajustées. L'historique des divisions vient du fournisseur, mis en cache en base.

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
la grille quotidienne donne exactement le TWR par sous-périodes. Un jour sans capital investi est exclu et signalé. Sur la page Risque, les jours sans capital (avant le premier apport, après un retrait total) sont hors série : ils n'entrent ni dans la volatilité, ni dans le Sharpe, ni dans le drawdown. Les courbes restent continues (niveau et drawdown inchangés ces jours-là), la volatilité glissante y est vide.

**TRI** (MWR, rendement pondéré par les capitaux) : le taux $r$ tel que
$\sum_k CF_k / (1 + r)^{(t_k - t_0)/365} = 0$. Flux du point de vue de l'investisseur : $-I_t$ daté du jour $t$,
$+O_t$ daté de $t + 1$, et la valeur finale comme dernier flux, datée du lendemain de la dernière clôture. La
racine est trouvée par la méthode de Brent, sur un intervalle élargi jusqu'à l'encadrer. Des flux tous de même
signe, ou sans racine réelle, renvoient une erreur explicite. Plusieurs racines sont possibles quand les flux
changent plusieurs fois de signe : la première trouvée est renvoyée.

**Annualisation.** $(1 + R)^{365/j} - 1$ sur $j$ jours calendaires, **seulement si $j \ge 365$** (convention
GIPS). En deçà, le rendement est affiché sur la période. Les indicateurs de risque des sections précédentes
sont annualisés sur la grille de jours ouvrés ($A = 261$).

**Données manquantes.** Un cours est reporté au plus 7 jours (week-ends, jours fériés). Au-delà, la valeur est
manquante, jamais nulle : le total est marqué incomplet et le TWR n'est pas calculé. Un jour de transaction sans
clôture prend le prix de la transaction, marqué comme tel.

### Risque et comparaison (portefeuille réel)

**Série de base.** Le TWR quotidien de la section précédente, par compte et au total. Les rendements du samedi et du
dimanche (crypto) sont composés dans le lundi suivant, ce qui donne des rendements de jours ouvrés. Une période
(origine, début d'année, 1, 3 ou 5 ans) est définie par sa date de base $b$ et couvre les jours de $]b,\ \text{date de
valorisation}]$. La valeur à la clôture de $b$ y est traitée comme un apport en début de premier jour : TWR et TRI de
la sous-période se calculent alors avec les mêmes fonctions. Une période plus longue que l'historique est refusée.

**Fréquences.**

| Mesures | Fréquence | Raison |
|---|---|---|
| Rendement, volatilité, drawdown, VaR, CVaR, Sharpe, Sortino, Calmar | quotidienne, jours ouvrés (A = 261 ; Calmar = rendement annualisé affiché / drawdown max) | propres à une série : plus d'observations, aucun biais de synchronisation |
| Bêta, alpha, corrélation, tracking error, ratio d'information | hebdomadaire (A = 52, semaines terminées le vendredi) | mesures croisées entre deux séries |

Euronext clôture à 17 h 30, New York à 22 h (heure de Paris). Un mouvement américain de fin de journée n'apparaît
que le lendemain dans les cours européens. En quotidien, la covariance entre une série européenne et une série
américaine est donc biaisée vers zéro (Scholes et Williams, 1977 ; Dimson, 1979). Mesure sur un même indice,
IWDA.AS (Amsterdam, EUR) contre URTH (New York, converti en EUR), de 2015 à 2026 : corrélation de **0,55 en
quotidien, 0,90 en hebdomadaire, 0,97 en mensuel**. L'hebdomadaire réduit fortement le biais sans l'annuler : les
deux places ferment encore à 4 h 30 d'écart le vendredi. D'où un **bêta de Dimson** en complément :
$\beta_D = \sum_{k=-1}^{1} b_k$ dans la régression $r_t = a + \sum_k b_k\, m_{t+k} + \varepsilon_t$ sur les semaines
$t-1$, $t$ et $t+1$. Le test `test_asynchronous_closes_bias_daily_correlation` décale une série d'un jour : la
corrélation quotidienne tombe à 0, l'hebdomadaire vaut 4/5 et le bêta de Dimson retrouve 1.

**Taux sans risque.** EONIA strictement avant le 01/10/2019, €STR ensuite, publiés par la BCE (ECB Data Portal :
`EON/D.EONIA_TO.RATE` et `EST/B.EU000A2X2A25.WT`). Depuis le 02/10/2019, la BCE définit l'EONIA comme €STR + 8,5
points de base : le raccord crée une marche de 8,5 pb sur le taux annuel, soit environ 0,0002 % par jour, sans effet
mesurable. Convention ACT/360 du marché monétaire : $rf_t = R_{t_0}/100 \times (t - t_0)/360$, avec $t_0$ la séance
précédente (un lundi porte trois jours). Un taux fixe saisi suit la même convention. L'interface indique les séries
utilisées sur la période affichée. Le taux variant dans le temps, les fonctions de `metrics.py` reçoivent les
rendements excédentaires $r_t - rf_t$ avec un taux nul : c'est la même formule, avec un taux variable.

**Références.** Indice dividendes réinvestis reconstruit à partir des clôtures (ajustées des seules divisions) et
des dividendes bruts à l'ex-date, net d'une retenue $\tau$, puis converti en euros au taux du jour :
$I_t = I_{t-1}\,(P_t + D_t (1-\tau))/P_{t-1}$, puis $I^{EUR}_t = I_t \times FX_t$. Sur 2025, la reconstruction brute de
QQQ donne +20,766 %, contre +20,773 % pour la clôture ajustée de Yahoo (méthode multiplicative).

| Série | Indice suivi | Écarts connus avec l'indice |
|---|---|---|
| **QQQ** (Invesco, New York, USD) | Nasdaq 100 | Frais de 0,18 %/an inclus dans le cours. Retenue de 15 % (convention France – États-Unis) appliquée par hypothèse. Un particulier français ne peut pas acheter QQQ (fonds américain non UCITS) : c'est un indicateur, pas un placement accessible. Conversion en EUR au taux Yahoo du jour, relevé à une autre heure que la clôture de New York. |
| **IWDA.AS** (iShares Core MSCI World, Amsterdam, EUR) | MSCI World (USD) | Frais de 0,20 %/an. Fonds irlandais capitalisant : les dividendes sont réinvestis dans le fonds, après la retenue qu'il subit (15 % sur les dividendes américains grâce à la convention Irlande – États-Unis, contre 30 % dans l'indice MSCI World Net). Il peut donc battre légèrement son indice net. Fonds en USD coté en EUR : le cours en euros intègre le change, ce qui est voulu. Vérification empirique, Yahoo ne donnant ni ISIN ni description : 11,91 %/an de 2015 à 2026, contre 11,98 % pour URTH converti en EUR. |

**Incertitude.** Intervalle de confiance à 95 % du Sharpe (quotidien) et du ratio d'information (hebdomadaire),
**robuste à l'autocorrélation**, d'après Lo (2002, rendements non i.i.d., estimateur GMM). Avec $\theta = (\mu, \sigma^2)$
et $SR = g(\theta) = \mu/\sigma$ :

```math
h_t = \big(r_t - \mu,\ (r_t - \mu)^2 - \sigma^2\big), \qquad
S = \Gamma_0 + \sum_{j=1}^{L}\Big(1 - \tfrac{j}{L+1}\Big)(\Gamma_j + \Gamma_j^\top), \qquad
V = \nabla g^\top S\, \nabla g,\ \ \nabla g = \Big(\tfrac{1}{\sigma},\ -\tfrac{\mu}{2\sigma^3}\Big),
```

avec $\Gamma_j$ l'autocovariance d'ordre $j$ des moments et $L = \lfloor 4\,(n/100)^{2/9} \rfloor$ retards (Newey et West :
6 pour 3 ans de séances, 4 pour 3 ans de semaines). Puis $SE_p = \sqrt{V/n}$ et $IC = SR \pm 1,96\, SE_p \sqrt{A}$,
centré sur le Sharpe affiché.

Version i.i.d., conservée en comparaison (`metrics.sharpe_ci`) : $V = 1 + SR_p^2/2$, que l'on retrouve exactement
quand les rendements sont gaussiens et sans autocorrélation (test `test_sharpe_ci_hac_matches_iid_without_autocorrelation`).
Pour une autocorrélation d'ordre 1 de 0,5, l'intervalle robuste est $\sqrt{3}$ fois plus large (test
`test_sharpe_ci_hac_widens_with_positive_autocorrelation`).

Sur données réelles, la version robuste n'élargit pas toujours l'intervalle. Elle corrige deux choses : l'autocorrélation
(une autocorrélation négative le resserre) et l'hypothèse gaussienne (des queues épaisses l'élargissent). Mesures sur
3 ans de séances, au 22/10/2026 :

| Série | Sharpe | IC i.i.d. | IC robuste | Autocorrélation d'ordre 1 |
|---|---|---|---|---|
| CW8.PA | 1,43 | [0,30 ; 2,56] | [0,17 ; 2,69] | −0,023 |
| IWDA.AS | 1,46 | [0,33 ; 2,59] | [0,20 ; 2,72] | −0,020 |
| QQQ | 1,22 | [0,08 ; 2,35] | [0,14 ; 2,30] | −0,062 |
| BTC-EUR | 0,88 | [−0,24 ; 1,99] | [−0,20 ; 1,95] | −0,048 |

Lo (2002) montre aussi qu'avec de l'autocorrélation, annualiser un Sharpe par $\sqrt{A}$ est biaisé, et propose le
facteur $\eta(q) = q / \sqrt{q + 2\sum_{k=1}^{q-1}(q-k)\rho_k}$ au lieu de $\sqrt{q}$. Il n'est **pas** appliqué : le
Sharpe affiché reste celui de `metrics.sharpe_ratio`. L'avertissement « historique court » donne la demi-largeur
i.i.d. d'un Sharpe nul, comme ordre de grandeur.

**Règles d'affichage.** Aucun indicateur annualisé sur moins d'un an. Avertissement visible sous 3 ans d'historique.
Mesures relatives masquées sous 26 semaines. Une valeur manquante rend la série incomplète, et rien n'est calculé.

### Diversification du portefeuille réel

**Poids.** Valeurs de marché en EUR à la date de valorisation : ce sont les poids réels, pas des poids constants.
L'unité est le titre (ISIN, sinon ticker), regroupé sur tous les comptes : une même ligne dans deux comptes ne crée pas
deux colonnes parfaitement corrélées. Les espèces sont exclues et les poids renormalisés sur les lignes risquées. Leur
variance étant nulle, la volatilité du portefeuille total vaut $\sigma_{total} = (1 - e)\,\sigma_{risqué}$, avec $e$ la part
d'espèces. Les deux chiffres sont affichés. La volatilité totale n'est calculée que si toutes les lignes détenues sont analysées : une ligne exclue (historique trop court, valeur manquante) a un risque inconnu. La part d'espèces est toujours rapportée au portefeuille entier.

**Données.** Rendements **hebdomadaires** en EUR de chaque ligne (cours du fournisseur × taux du jour, jours ouvrés,
semaines au vendredi), sur la fenêtre de la période choisie, quelle que soit la date d'achat. Les mesures croisées
utilisent l'hebdomadaire pour la raison donnée plus haut (clôtures non synchrones).

**Historique minimal : 52 semaines.** L'erreur-type d'une corrélation estimée vaut environ $(1-\rho^2)/\sqrt{T}$, soit
0,14 pour $\rho = 0$ et $T = 52$ : en deçà, une corrélation de 0,3 n'est pas distinguable de 0. Une ligne qui a moins de
52 semaines de cours sur la fenêtre est exclue et signalée, jamais complétée. Une ligne partielle, qui a au moins 52
semaines sans couvrir toute la fenêtre, est gardée **sans réduire la fenêtre des autres**.

**Covariance par paires.** Chaque élément $\Sigma_{ij}$ est estimé sur les semaines communes aux lignes $i$ et $j$. Sans
donnée manquante, c'est exactement la covariance empirique (testé). Avec des lignes partielles, la matrice peut ne pas
être semi-définie positive. Sa matrice de corrélation est alors remplacée par la matrice de corrélation la plus proche
en norme de Frobenius (Higham, 2002 : projections alternées avec correction de Dykstra, testé sur l'exemple publié), puis
remise à l'échelle par les écarts-types.

**Garde-fou.** On affiche la norme relative de la correction, $\lVert \tilde C - C \rVert_F / \lVert C \rVert_F$, et la plus
grande variation d'un coefficient de corrélation. Le seuil vaut $1/\sqrt{T_{min}}$, soit l'erreur-type d'une corrélation
estimée sur la plus courte période commune (0,14 pour 52 semaines). Au-delà, la correction déplace un coefficient de
plus que le bruit d'estimation : un avertissement s'affiche, avec la comparaison « lignes partielles exclues ».

**Estimateurs** (réglage, Ledoit-Wolf à corrélation constante par défaut) :

| Estimateur | Cible $F$ | Effet |
|---|---|---|
| Ledoit-Wolf, corrélation constante (2004, « Honey, I Shrunk the Sample Covariance Matrix ») | variances conservées, toutes les corrélations égales à la moyenne $\bar r$ | réduit le bruit sans changer le niveau moyen des corrélations |
| Ledoit-Wolf, identité réduite (2004, « A Well-Conditioned Estimator… ») | $\frac{\mathrm{tr}\,S}{N} I$ | **tire les corrélations vers zéro et gonfle donc l'ENB** quand un facteur commun existe |
| Empirique | aucune | non biaisée, mais bruitée quand $T$ est petit devant $N$ |

$\hat\Sigma = \delta F + (1-\delta) S$, avec l'intensité optimale $\delta \in [0, 1]$ des articles (testé contre une
transcription des formules publiées). Avec des données manquantes, les moments $\pi$, $\rho$ et $\gamma$ sont calculés par
paires, et l'intensité utilise $T_{min}$ : c'est une adaptation prudente (moins de données, plus de contraction),
documentée comme telle.

**Effet du choix sur l'ENB.** Simulation à covariance connue avec le code de l'application : 17 lignes, poids tirés
au hasard, 40 échantillons par cas (moyenne ± écart-type).

| Structure | T | Vraie | Empirique | LW corrélation constante | LW identité |
|---|---|---|---|---|---|
| Un facteur commun — ENB ACP | 150 | 1,14 | 1,14 ± 0,02 | 1,14 ± 0,02 (δ = 0,25) | 1,15 ± 0,02 (δ = 0,03) |
| | 60 | 1,14 | 1,16 ± 0,05 | 1,17 ± 0,04 (δ = 0,56) | **1,19 ± 0,06** (δ = 0,09) |
| Un facteur commun — ENB torsion | 150 | 16,45 | 16,39 ± 0,11 | 16,48 ± 0,09 | 16,37 ± 0,12 |
| | 60 | 16,45 | 16,33 ± 0,20 | 16,49 ± 0,13 | 16,21 ± 0,23 |
| Trois blocs — ENB ACP | 60 | 1,11 | 1,15 ± 0,07 | 1,14 ± 0,04 (δ = 0,47) | **1,17 ± 0,07** (δ = 0,11) |
| Trois blocs — ENB torsion | 60 | 15,58 | 15,44 ± 0,39 | 15,70 ± 0,32 | 15,27 ± 0,41 |

Lecture : l'ENB par ACP, dominé par le premier facteur, est peu sensible à l'estimateur. Avec 150 semaines, les trois
estimateurs se valent. Quand l'historique raccourcit (60 semaines), la cible identité **surestime** l'ENB par ACP et
augmente la dispersion. La corrélation constante reste la plus proche de la vérité et la plus stable. Sur le portefeuille
de démonstration (7 lignes, 1 an au 24/10/2026, modèle à deux facteurs), l'ENB par ACP vaut 2,17 avec la corrélation
constante, 2,12 avec l'identité et 2,08 avec l'empirique. Ici la cible identité ne gonfle pas l'ENB : elle rapproche
aussi les variances, ce qui réduit le poids du bitcoin (volatilité 65 %) dans le premier facteur. Sur un seul
échantillon, l'écart entre estimateurs reste inférieur à l'erreur d'estimation.

**Données de démonstration.** Modèle à deux facteurs indépendants (marché mondial et technologie, volatilité 20 %
chacun), plus un bruit propre à chaque ligne, avec des queues épaisses (Student à 4 degrés de liberté). La corrélation
théorique vaut $\rho_{ij} = 0,2^2\,(\beta_i\beta_j + \gamma_i\gamma_j)/(\sigma_i\sigma_j)$, avec $\beta$ l'exposition
au marché et $\gamma$ l'exposition à la technologie (testé sur un long échantillon). Le facteur technologie sépare le
Nasdaq du MSCI World : corrélation hebdomadaire en EUR de 0,86 sur 2021-2026, au lieu de 0,96 avec un seul facteur
(environ 0,85 à 0,90 en réalité). Ces données sont fictives.

**Mesures.** Celles de `metrics.py` (`risk_contributions`, `pca_diversification`, `minimum_torsion_diversification`),
auxquelles on passe la covariance estimée (paramètre `cov`). Contributions d'Euler par ligne. Par compte et par classe,
elles sont exactes par linéarité : $RC_{position} = w_{position}\,(\Sigma w)_{ligne} / \sigma^2$. Le texte
d'interprétation suit des règles écrites :
- facteur commun si le premier facteur porte au moins 60 % de la variance **et** si l'ENB torsion vaut au moins 2 fois
  l'ENB ACP ;
- concentration si l'ENB torsion est inférieur à la moitié du nombre de lignes ;
- sinon, risque réparti.

**Simulateur** (rien n'est écrit) :
- argent frais : $w' = (w + x\,e_Y)/(1 + x)$, et la part d'espèces devient $e' = e/(1 + x(1-e))$ ;
- réallocation : $w' = (1-x)\,w + x\,e_Y$.

Avant et après utilisent la **même** covariance. Pour un nouveau ticker, elle est estimée avec lui, à poids nul avant.
Le drawdown historique suppose des poids constants (rééquilibrage quotidien) sur les jours où toutes les lignes ont un
cours : c'est une hypothèse de simulation, différente du portefeuille réel, dont les poids dérivent. Ajouter 0 % ne
change rien (testé, dans les deux modes).

**Recoupement réel** (4 lignes, dont une en USD et une crypto, estimateur empirique, 1 an au 23/10/2026) : corrélations
identiques à un calcul indépendant à 4·10⁻⁵ près (arrondi), volatilité 14,0695 % des deux côtés.

### Valorisation : DCF inversé

**Question posée.** On ne cherche pas une « valeur juste ». On cherche la croissance annuelle $g$ du flux disponible
que le prix actuel suppose pendant $N$ ans, avant une croissance terminale $g_{term}$ à perpétuité. Le résultat est une
lecture d'hypothèses, jamais une recommandation. La phrase affichée reste neutre : « Le prix actuel suppose une
croissance du flux disponible de X % par an pendant N ans, puis de Y % par an à perpétuité, avec un coût du capital
de Z %. »

**Périmètre.** Seules les actions sont analysées.
- ETF et fonds : ils se lisent par les sociétés qu'ils contiennent, ils n'ont pas de flux propre.
- Cryptoactifs : aucun flux à actualiser.
- Banques et assurances (industrie Yahoo commençant par `Banks`, `Insurance -` ou `Reinsurance`, ou forçage sur la
  fiche) : la dette est leur matière première, le flux disponible pour l'entreprise n'a pas de sens.

**Flux et valeur : ne jamais mélanger.** Le flux retenu est le FCFF, flux disponible pour l'**entreprise**, avant
paiement des créanciers. Il est actualisé au coût du capital et comparé à la **valeur d'entreprise** :

$$VE = \text{cours} \times \text{change} \times \text{actions diluées} + \text{dette} - \text{trésorerie et placements} - \text{placements non courants} + \text{intérêts minoritaires}$$

Comparer un FCFF à la seule capitalisation ignorerait la dette. Comparer un flux des actionnaires (après intérêts) à
la VE compterait la dette deux fois. Le code n'offre qu'une voie (`implied_growth(fcff0, ev, …)`), ce qui rend le
mélange impossible. Les minoritaires sont ajoutés parce que le FCFF consolidé inclut leur part.

**Placements financiers non courants.** Des titres détenus à plus d'un an (obligations, titres disponibles à la
vente) sont un actif financier comme la trésorerie : leurs revenus ne sont pas dans le FCFF, ils sont donc retranchés
de la VE. Champ `lt_investments`, lu chez Yahoo (ligne « Investmentin Financial Assets ») ou saisi à la main. Les
participations mises en équivalence (« Long Term Equity Investment », par exemple la part d'ASML dans Carl Zeiss SMT)
ne sont pas retranchées : ce sont des participations opérationnelles, pas des placements. Exemple : Apple détient
77,7 Md USD de titres négociables non courants au 27/09/2025 (10-K), en plus de 54,7 Md USD de trésorerie et placements
courants ; les ignorer surestimerait la VE de 1,5 % et le g implicite de 0,2 point (22,8 % au lieu de 22,6 %).
Absent chez le fournisseur, le champ reste « manquant » (jamais 0). Le calcul n'est pas bloqué, parce que la plupart
des sociétés n'en ont pas de significatifs, mais les placements ne sont pas retranchés et un avertissement le dit :
la VE et le g implicite peuvent être surestimés. Saisir 0 confirme l'absence et retire l'avertissement.

**FCFF par exercice.**

$$FCFF = OCF - |capex| + \text{intérêts} \times (1 - t) - \text{rémunération en actions}$$

- **Intérêts** : on ne les rajoute que s'ils ont été retranchés de l'OCF. C'est toujours le cas en US GAAP. En IFRS,
  la société choisit de classer les intérêts versés en exploitation ou en financement : c'est un attribut du titre,
  affiché et modifiable (« exploitation » par défaut).
- **t** : taux effectif moyen, $\sum \text{impôt} / \sum \text{résultat avant impôt}$, sur les exercices du FCF de
  départ ; ou taux légal saisi à la main. Jamais un taux inventé.
- **Rémunération en actions** : retranchée par défaut. Elle n'est pas décaissée, donc l'OCF l'ajoute ; mais elle
  dilue les actionnaires, c'est une charge réelle. Option désactivable dans les réglages ou sur la fiche.
- **Données manquantes** : intérêts, impôt, rémunération en actions ou un exercice de la moyenne manquant ⇒ calcul
  **bloqué**, l'exercice et le champ sont nommés. Jamais de zéro par défaut. Remèdes : la saisie manuelle (voie
  préférée, avec une note de source), ou une approximation acceptée explicitement et mémorisée pour ce titre :
  - « OCF − capex » sans les intérêts : le FCFF est sous-estimé, donc **le g implicite est surestimé** ;
  - VE sans minoritaires : la VE est sous-estimée, donc le g implicite est sous-estimé.
  Chaque approximation acceptée est signalée sur la fiche et dans le récapitulatif.

**FCF de départ.** Moyenne des $n$ derniers FCFF ($n = 3$ par défaut, réglable de 1 à 5), pour lisser une année
atypique (variation de besoin en fonds de roulement, investissement exceptionnel). Une fenêtre trouée n'est pas moyennée.
Si $FCF_0 \le 0$, le DCF inversé est refusé : aucune croissance ne transforme un flux négatif en valeur positive.

**Normes comptables et locations.** La norme est un attribut du **titre**, pas de la cotation : ASML, société
néerlandaise, publie ses comptes principaux en US GAAP ; une ADR américaine peut publier en IFRS. La valeur par défaut
(US GAAP si la cotation est américaine, IFRS sinon) est marquée « proposée » jusqu'à confirmation, avec un rappel de
vérification dans le rapport annuel.
- **IFRS 16** : les loyers sont classés en financement (remboursement de dette locative), l'OCF ne les a pas payés.
  La dette inclut donc les dettes locatives. Si elles manquent : calcul bloqué, saisie demandée (0 si aucune).
- **US GAAP (ASC 842)** : les loyers des locations simples sont déjà déduits de l'OCF. La dette **exclut** donc les
  dettes locatives. Les locations-financement (faibles chez les sociétés détenues) sont exclues elles aussi : limite
  mineure (Apple : 1,2 Md USD pour une VE d'environ 5 260 Md USD).

**Dette financière : construite, pas lue.** La ligne « Total Debt » de Yahoo n'a pas le même périmètre selon la
société. Elle inclut les dettes locatives pour LVMH et NVIDIA, pas pour Apple (98,7 Md USD = emprunts et billets de
trésorerie seuls, alors que le 10-K publie 12,5 Md USD de locations simples). On construit donc :
- dette financière = « Long Term Debt » + « Current Debt » (à défaut : « Current Debt And Capital Lease Obligation »
  − « Current Capital Lease Obligation ») ;
- dettes locatives = « Capital Lease Obligations » (à défaut : long terme + courant).

Un terme absent rend le total manquant. Ce défaut a été trouvé par le recoupement ci-dessous.

**Décalage de dates.** Le cours est celui du jour ; dette, trésorerie, minoritaires et actions viennent du dernier
bilan annuel. Les deux dates sont affichées, et un avertissement le rappelle.

**Équation.** Avec $k$ le coût du capital :

$$V(g) = \sum_{t=1}^{N} \frac{FCF_0 (1+g)^t}{(1+k)^t} + \frac{FCF_0 (1+g)^N (1+g_{term})}{(k - g_{term})(1+k)^N} = VE$$

Si $FCF_0 > 0$, $V$ est strictement croissante en $g$ : la solution est unique. Elle est cherchée par la méthode de
Brent sur $[-99\ \% ; +200\ \%]$. Erreurs explicites : $k \le g_{term}$ (valeur terminale infinie), $FCF_0 \le 0$,
$VE \le 0$, pas de solution dans l'intervalle.

**Coût du capital.**
- **k commun** (par défaut, et toujours dans le récapitulatif pour que les lignes restent comparables) : taux d'État
  à 10 ans de la devise des comptes + prime de risque actions, avec $\beta = 1$.
  - EUR : courbe AAA de la zone euro à 10 ans (BCE, `YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y`) ;
  - USD : Treasury à 10 ans (FRED, `DGS10`) ;
  - autre devise, ou taux indisponible : k à saisir dans les réglages.

  C'est le coût des fonds propres d'une entreprise moyenne, un peu au-dessus d'un WACC typique (la dette coûte moins
  cher après impôt). Le g implicite est donc légèrement plus élevé : la lecture est prudente.
- **Prime de risque : 4,20 % par défaut.** C'est la dernière prime implicite du S&P 500 publiée par Damodaran, au
  1er octobre 2026, selon sa méthode principale (flux des 12 derniers mois, taux de distribution ajusté). La fourchette
  publiée va de 3,30 % à 5,67 % selon la méthode. Source et date sont affichées dans les Réglages ; la valeur reste
  modifiable. À mettre à jour à la main : l'application ne la télécharge pas.
- **k MEDAF** (option des réglages, et toujours affiché à côté sur la fiche) :
  - $k_e = r_f + \beta_{Blume} \times \text{prime}$, avec $\beta_{Blume} = 0,67\,\beta + 0,33$, $\beta$ de Dimson
    hebdomadaire sur 5 ans en EUR contre le MSCI World ;
  - $k_d$ = intérêts / dette moyenne des deux derniers bilans, après impôt ;
  - pondérations aux valeurs de marché (capitalisation, dette) ;
  - un élément manquant rend le k MEDAF « manquant » ; le k commun reste disponible.

**Croissance terminale : 2 %.** C'est la cible d'inflation de la BCE et de la Fed, c'est-à-dire une croissance réelle
nulle à perpétuité. Elle reste sous la croissance nominale de long terme (inflation et croissance réelle, environ
3 à 4 %) : aucune entreprise ne peut croître durablement plus vite que l'économie. Réglable.

**Horizon : 10 ans.** C'est la convention usuelle pour une période de croissance explicite. Réglable de 1 à 30 ans.

**Lecture.**
- Croissance historique du FCFF (même définition) et du chiffre d'affaires : taux annuel composé sur les exercices
  disponibles, avec leur nombre ; « non significatif » si la valeur de départ ou d'arrivée est négative ou nulle ;
  « manquant » s'il y a moins de deux exercices. C'est un repère sur 3 à 4 ans, pas une prévision sur 10.
- Sensibilité : $k \pm 1$ et $\pm 2$ points × $g_{\text{term}} \in (1\% ;\ 1.5\% ;\ 2\% ;\ 2.5\% ;\ 3\%)$. Le g implicite croît
  avec $k$ et décroît avec $g_{term}$ (testé). Une case impossible affiche sa raison, jamais un nombre.

**Recoupement réel** (données Yahoo lues par l'application le 24/10/2026, contre les publications des sociétés).

*Apple (US GAAP), 10-K de l'exercice clos le 27/09/2025, chiffres XBRL de la SEC (accession 0000320193-25-000079), en Md USD :*

| Poste | 10-K 2025 | Yahoo 2025 | 10-K 2024 | Yahoo 2024 | Écart |
|---|---|---|---|---|---|
| Chiffre d'affaires | 416,161 | 416,161 | 391,035 | 391,035 | aucun |
| OCF | 111,482 | 111,482 | 118,254 | 118,254 | aucun |
| Capex | 12,715 | 12,715 | 9,447 | 9,447 | aucun |
| Rémunération en actions | 12,863 | 12,863 | 11,688 | 11,688 | aucun |
| Résultat avant impôt | 132,729 | 132,729 | 123,485 | 123,485 | aucun |
| Impôt | 20,719 | 20,719 | 29,749 | 29,749 | aucun |
| Dette financière (long terme + courant + billets de trésorerie) | 98,657 | 98,657 | 106,629 | 106,629 | aucun |
| Trésorerie et placements courants | 54,697 | 54,697 | 65,171 | 65,171 | aucun |
| Actions diluées (moyenne, Md) | 15,005 | 15,005 | 15,408 | 15,408 | arrondi |
| Charge d'intérêts | non publiée à part | manquante | non publiée à part | manquante | voir ci-dessous |
| Dettes locatives (locations simples) | 12,490 | manquantes | 11,534 | manquantes | sans effet en US GAAP |

- **Intérêts** : depuis l'exercice 2024, Apple ne publie plus sa charge d'intérêts à part (elle est incluse dans
  « Other income/(expense), net »). Le blocage est donc juste, et l'approximation OCF − capex est la seule voie sans
  invention. Avec environ 99 Md USD de dette, l'effet est faible devant un FCFF de 90 Md USD.
- **Placements non courants** : 77,7 Md USD dans le 10-K, identiques chez Yahoo (« Investmentin Financial Assets »),
  désormais lus et retranchés de la VE (champ `lt_investments`). Le recalcul indépendant ci-dessous date d'avant ce
  champ ; avec lui, la VE passe de 5 262 à 5 184 Md USD et le g implicite de 22,8 % à 22,6 %.
- **Minoritaires** : Apple n'en a pas ; Yahoo ne publie pas la ligne, à saisir 0.

*LVMH (IFRS), communiqué des résultats annuels 2025 du 27/01/2026, en M€ :*

| Poste | LVMH | Yahoo | Écart |
|---|---|---|---|
| Ventes 2025 | 80 807 | 80 807 | aucun |
| Ventes 2024 | 84 683 | 84 682 | arrondi |
| Dette financière nette 2025 (dette financière − trésorerie et placements) | 6 857 | 20 344 − 13 502 = 6 842 | 15 (0,2 %) |
| Dette financière nette 2024 | 9 228 | 22 941 − 13 587 = 9 354 | 126 (1,4 %) |
| Cash-flow disponible d'exploitation 2025 | 11 333 | OCF − capex = 14 205 | 2 872 |

- La dette financière nette de LVMH exclut les dettes locatives (16,4 Md€ à fin 2025), comme notre champ
  `financial_debt`. Les petits écarts viennent probablement des instruments dérivés de couverture, que LVMH intègre
  à sa dette nette. Le « Total Debt » de Yahoo (36,7 Md€) inclut au contraire les locations.
- Le « cash-flow disponible d'exploitation » de LVMH retranche aussi les remboursements de dettes locatives
  (environ 2,9 Md€, l'écart observé). En IFRS, notre FCFF ne les retranche pas, parce que la VE inclut les dettes
  locatives : les deux conventions sont cohérentes, il ne faut pas les croiser.
- La rémunération en actions de LVMH est absente chez Yahoo : la fiche bloque jusqu'à une saisie (montant du
  document d'enregistrement universel) ou la désactivation de l'option.

*g recalculé indépendamment* (script séparé : formules écrites à la main, bissection au lieu de Brent), mêmes données
et mêmes taux (FRED 4,96 % et BCE 3,38 % au 22/10/2026, prime 5 %, N = 10, $g_{term}$ = 2 %) :

| Titre | Hypothèses | FCF₀ | VE | g indépendant | g application |
|---|---|---|---|---|---|
| AAPL | US GAAP, OCF − capex, rémunération en actions retranchée, k = 9,96 % | 90,59 Md USD | 5 261,5 Md USD | 22,8289 % | 22,8289 % |
| MC.PA | IFRS, intérêts en exploitation, sans rémunération en actions, k = 8,38 % | 13,51 Md€ | 217,8 Md€ | 2,1213 % | 2,1213 % |

Écart entre les deux calculs : moins de $10^{-15}$.

**Contrôle de vraisemblance.** La fiche affiche, à côté du g implicite, le multiple $VE / FCF_0$ observé. Les deux
disent la même chose sous deux formes : `implied_multiple(g, k, N, g_term)` = $V(g)$ pour $FCF_0 = 1$ redonne exactement
le multiple observé (testé). Repère : avec $g = 0$, $k = 9,16\ \%$ et $g_{term} = 2\ \%$, le multiple vaut environ 12 ;
un multiple de 50 ou plus suppose une croissance forte et longue.

*Apple, vérification à la main (24/10/2026, réglages par défaut : prime 4,20 %, Treasury 4,96 % au 22/10/2026,
k = 9,16 %, N = 10, $g_{term}$ = 2 %, rémunération en actions déduite, approximation OCF − capex) :*

| Élément | Valeur |
|---|---|
| FCFF 2023 / 2024 / 2025 (OCF − capex − rémunération en actions) | 88,75 / 97,12 / 85,90 Md USD |
| FCFF de départ (moyenne) | 90,59 Md USD |
| Rémunération en actions déduite (moyenne) | 11,80 Md USD, soit 11,5 % du flux avant déduction |
| VE = 5 217,6 (capitalisation) + 98,7 (dette) − 54,7 (trésorerie) − 77,7 (placements non courants) | 5 183,8 Md USD |
| Multiple VE / FCF de départ | 57,2 (rendement du flux : 1,75 %) |
| g implicite | 20,7 % par an pendant 10 ans |
| sans déduire la rémunération en actions | multiple 50,6, g 19,1 % |
| Charge d'intérêts | publiée par Yahoo jusqu'en 2023 (3,93 Md USD), manquante en 2024 et 2025 |
| avec une prime de 5 % (k = 9,96 %) | g 22,6 % |

Lecture : le calcul est juste (recoupé deux fois), mais l'hypothèse qu'il révèle est très éloignée de l'historique.
20,7 % par an pendant 10 ans multiplie le flux par 6,6, à environ 600 Md USD en 2035, soit 1,4 fois le chiffre d'affaires
de 2025 (416 Md USD), alors que le FCFF n'a pas progressé sur 4 exercices et le chiffre d'affaires de 3 % par an environ.
L'approximation OCF − capex biaise g vers le haut, mais faiblement : en reprenant la dernière charge publiée
(3,9 Md USD en 2023, soit 3,2 Md USD après impôt) comme ordre de grandeur, g passe de 20,7 % à 20,3 %. Le prix ne s'explique donc, dans ce modèle, que par une croissance future bien supérieure au
passé, ou par un coût du capital nettement plus bas que 9 %. C'est une lecture du prix, pas un avis sur le titre.

### Limites

- Toutes ces mesures sont des **estimations sur le passé**. Pour des rendements i.i.d., l'erreur-type du Sharpe estimé sur $n$ périodes vaut $\sqrt{(1 + S_p^2/2)/n}$, avec $S_p$ le Sharpe par période (Lo, 2002). En données quotidiennes, $S_p$ est petit et l'erreur-type du Sharpe annualisé se réduit à environ $1/\sqrt{T}$, avec $T$ la durée en années. Sur 5 ans : environ 0,45. Un Sharpe estimé de 0,8 a donc un intervalle de confiance à 95 % d'environ $0,8 \pm 1,96 \times 0,45$, soit $[-0,1\ ;\ 1,7]$.
- La VaR historique ne prévoit pas les crises absentes de l'échantillon.
- Les données Yahoo Finance sont gratuites et non garanties : erreurs ponctuelles possibles.
- Le DCF inversé dépend entièrement de $k$ et de $g_{term}$ (voir la sensibilité) : c'est une lecture du prix, pas une estimation de valeur.

### Sources

- Higham, N. J. (2002). *Computing the Nearest Correlation Matrix — A Problem from Finance*. IMA Journal of Numerical Analysis.
- Ledoit, O., Wolf, M. (2004). *Honey, I Shrunk the Sample Covariance Matrix*. Journal of Portfolio Management.
- Ledoit, O., Wolf, M. (2004). *A Well-Conditioned Estimator for Large-Dimensional Covariance Matrices*. Journal of Multivariate Analysis.
- Newey, W. K., West, K. D. (1994). *Automatic Lag Selection in Covariance Matrix Estimation*. Review of Economic Studies.

- Scholes, M., Williams, J. (1977). *Estimating Betas from Nonsynchronous Data*. Journal of Financial Economics.
- Dimson, E. (1979). *Risk Measurement When Shares Are Subject to Infrequent Trading*. Journal of Financial Economics.

- Sharpe, W. F. (1994). *The Sharpe Ratio*. Journal of Portfolio Management.
- Lo, A. W. (2002). *The Statistics of Sharpe Ratios*. Financial Analysts Journal.
- Meucci, A. (2009). *Managing Diversification*. Risk.
- Meucci, A., Santangelo, A., Deguest, R. (2015). *Risk Budgeting and Diversification Based on Optimized Uncorrelated Factors*. Risk.

- Damodaran, A. *Implied Equity Risk Premium*, mise à jour du 1er octobre 2026, pages.stern.nyu.edu/~adamodar (consulté le 24/10/2026).
- Blume, M. E. (1971). *On the Assessment of Risk*. Journal of Finance.
- Apple Inc., formulaire 10-K de l'exercice 2025, données XBRL de la SEC (data.sec.gov, CIK 0000320193).
- LVMH, communiqué des résultats annuels 2025, 27 janvier 2026 (lvmh.com).
