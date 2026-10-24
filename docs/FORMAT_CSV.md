# Format d'import CSV des transactions

Un fichier par import, une ligne par opération. Exemple complet : [`examples/transactions_exemple.csv`](../examples/transactions_exemple.csv).

## Règles générales

- **Séparateur** : `;` (recommandé). `,` et la tabulation sont reconnus quand l'en-tête n'a pas de `;`.
- **Encodage** : UTF-8 (avec ou sans BOM). Windows-1252 est accepté, pour un fichier enregistré depuis Excel.
- **Dates** : `AAAA-MM-JJ` ou `JJ/MM/AAAA`.
- **Nombres** : la virgule décimale française est acceptée. `1 234,56`, `1234,56`, `1.234,56` et
  `1,234.56` valent tous 1234,56 : quand les deux séparateurs apparaissent, le dernier est le décimal.
  Un point seul suivi de groupes de trois chiffres (`1.500`, `12.345.678`) est **refusé** : milliers à la
  française ou décimale à l'anglaise, il est ambigu. Écrivez `1500` ou `1,5`.
  Le symbole `€` et les espaces insécables sont ignorés. Aucune valeur n'est arrondie.
- **En-tête** obligatoire, dans n'importe quel ordre. Les accents et la casse des noms de colonnes sont ignorés
  (`Quantité` = `quantite`). Une colonne inconnue est refusée, pour qu'une faute de frappe ne fasse pas
  disparaître une donnée en silence.
- Les **comptes** doivent exister avant l'import (page Comptes et titres), car leur convention de flux doit être
  choisie explicitement. Le nom est comparé sans tenir compte de la casse.

## Divisions d'actions

Saisissez les quantités et prix **d'origine**, tels qu'ils figuraient sur l'avis d'opération : 2 NVDA à 900 USD
achetées avant la division par 10 de juin 2024 se saisissent `2;900`, pas `20;90`. L'application ajuste au calcul
à partir de l'historique des divisions, et liste chaque ajustement sur la page Positions.

## Colonnes

| Colonne | Obligatoire | Contenu |
|---|---|---|
| `date` | oui | Date de l'opération |
| `compte` | oui | Nom exact du compte |
| `type` | oui | `ACHAT`, `VENTE`, `DIVIDENDE`, `DEPOT`, `RETRAIT`, `FRAIS` (`DÉPÔT` accepté) |
| `ticker` | achat, vente, dividende | Ticker Yahoo Finance de la cotation : `PANX.PA`, `AAPL`, `BTC-EUR` |
| `isin` | non | ISIN du titre. Facultatif, absent pour une crypto |
| `quantite` | achat, vente | Quantité, fractions acceptées |
| `prix` | achat, vente | Prix unitaire dans la devise de la cotation |
| `montant` | dividende, dépôt, retrait, frais | Achat/vente : montant brut hors frais, facultatif (sinon quantité × prix ; contrôlé à 1 centime près). Dividende : montant **net** reçu. Dépôt, retrait, frais : montant positif |
| `frais` | non | Frais de courtage d'un achat ou d'une vente, dans la devise de la transaction. Vide = 0. Refusés sur les autres types : saisir un dividende net, ou une ligne FRAIS séparée |
| `devise` | non | Devise de la transaction. Vide = devise de la cotation (ou EUR sans ticker). Doit être égale à la devise de la cotation |
| `taux_change` | non | Taux appliqué par le courtier : euros pour 1 unité de devise (ex. `0,9150` pour 1 USD). Vide = taux de marché du jour |
| `retenue` | non | Retenue à la source sur un dividende (information) |
| `note` | non | Texte libre |
| `classe` | non | `action`, `etf`, `crypto`, `autre`. Utilisée à la création de la cotation |

## Déroulement

1. **Aperçu** : le fichier est lu et validé, rien n'est écrit. Pour chaque ticker inconnu, le fournisseur de données
   est interrogé (existence, devise, nom). Les erreurs sont listées ligne par ligne.
2. **Import** : possible seulement si l'aperçu ne contient aucune erreur. Tout est écrit en une seule transaction :
   tout passe, ou rien.
3. **Doublons** : une ligne identique à une transaction déjà en base (même compte, date, type, ticker, quantité,
   prix, montant et frais) est ignorée et signalée. Réimporter un même fichier n'ajoute donc rien. Deux lignes
   identiques à l'intérieur d'un même fichier sont en revanche importées toutes les deux (deux ordres le même jour).

L'historique complet est validé, transactions existantes comprises. Une vente supérieure à la quantité détenue,
un dépôt sur un compte « titres seuls » ou une devise incohérente bloquent l'import.

## Convention de flux selon le compte

- Compte **avec espèces** : saisissez aussi les `DEPOT` et `RETRAIT`. Sans eux, le solde d'espèces devient négatif
  et un avertissement le signale.
- Compte **titres seuls** : `DEPOT` et `RETRAIT` sont refusés. Les achats sont des apports, les ventes et dividendes
  des retraits.

## Passer d'un relevé de courtier à ce format

Les exports Trade Republic et Fortuneo ne sont pas lus directement (voir les limites dans le README). Il faut
les recopier dans ce format, en général depuis un tableur : une colonne par champ, puis « Enregistrer sous
CSV (séparateur point-virgule) ».
