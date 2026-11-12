# Recette de la 1.0.0

Ce document liste les vérifications à faire sur une vraie instance Home Assistant
avant de publier la 1.0.0 (cahier des charges, sections 9 et 10). Les tests
automatiques couvrent les règles de calcul ; la recette vérifie ce qu'ils ne peuvent
pas voir : les vraies données téléchargées, le vrai fuseau horaire, le tableau de
bord Énergie et le comportement sur plusieurs jours.

## Références

Chaque valeur affichée est comparée à une source officielle :

- **Prix et abonnement** : la grille de la CRE sur data.gouv.fr, jeu de données
  « Historique des tarifs réglementés de vente d'électricité pour les consommateurs
  résidentiels », un fichier par option (Base, HP/HC, Tempo). La ligne en vigueur
  est celle de votre puissance (`P_SOUSCRITE`) dont la date de fin (`DATE_FIN`) est
  vide. En contrôle complémentaire, la grille tarifaire publiée par EDF (attention à
  l'unité de l'abonnement : par mois ou par an).
- **Couleurs Tempo** : la couleur publiée par RTE ou affichée par EDF (site ou
  application).
- **Heures creuses** : celles indiquées sur votre facture.

| Capteur | Colonne de la grille CRE |
|---|---|
| Abonnement annuel | `PART_FIXE_TTC` (€/an) |
| Prix Base | `PART_VARIABLE_TTC` |
| Prix heures pleines, heures creuses | `PART_VARIABLE_HP_TTC`, `PART_VARIABLE_HC_TTC` |
| Prix jour bleu, blanc, rouge | `PART_VARIABLE_{HP\|HC}{Bleu\|Blanc\|Rouge}_TTC` |

Les capteurs affichent 4 décimales ; les diagnostics du contrat donnent les valeurs
exactes de la ligne en vigueur (`grid.row_in_force`).

## Préparation

- Installer la dernière version publiée par HACS et redémarrer Home Assistant.
- Ajouter un contrat par option à vérifier, même celles que vous n'avez pas : un
  contrat ne fait que lire des données publiques. Les contrats en trop se suppriment
  à la fin de la recette.
- Garder le journal à portée de main : Paramètres → Système → Journaux, filtre
  `trve_edf`.

## Vérifications

### Installation et configuration

- [ ] L'intégration s'installe par HACS dans la version attendue ; son icône
  s'affiche dans Paramètres → Appareils et services (Home Assistant 2026.3 ou plus
  récent ; HACS affiche une icône générique pour un dépôt personnalisé).
- [ ] La liste des puissances proposées correspond aux puissances en vigueur dans la
  grille CRE de l'option.
- [ ] HP/HC : une saisie d'heures creuses invalide affiche un message précis ; une
  saisie valide est acceptée et réapparaît, normalisée, dans les options.
- [ ] Plusieurs contrats fonctionnent en même temps, chacun avec ses capteurs.

### Prix

- [ ] Chaque prix et l'abonnement sont égaux aux valeurs de la ligne en vigueur de la
  grille CRE, pour chaque option.
- [ ] Les diagnostics montrent la bonne ligne en vigueur (dates de début et de fin,
  puissance) et une grille de confiance (`grid.trusted`).

### Période et prix actuel

- [ ] Base : la période est toujours « Base » et le prix actuel égal au prix Base.
- [ ] HP/HC : la période et le prix actuel changent exactement aux heures de début et
  de fin des heures creuses (historique du capteur : changement à la seconde près,
  heure française).
- [ ] « Prochain changement de prix » indique le prochain changement de période et se
  met à jour au moment du changement.

### Tempo

- [ ] La couleur en cours change à 6 h, pas à minuit : entre minuit et 6 h, elle
  reste celle de la journée Tempo commencée la veille.
- [ ] Les couleurs d'hier et d'aujourd'hui sont celles publiées pour ces dates (la
  journée Tempo d'une date commence à 6 h ce jour-là).
- [ ] La couleur de demain reste « Inconnu » jusqu'à sa publication, puis apparaît
  dans le quart d'heure (vérifications à partir de 10 h 30) et correspond à la
  couleur officielle.
- [ ] Les heures creuses vont de 22 h à 6 h ; à 6 h, le prix actuel passe au prix
  heures pleines de la couleur du nouveau jour.
- [ ] Le prix actuel est égal au prix de la couleur en cours et de la période en
  cours.

### Tableau de bord Énergie

- [ ] Le capteur « Prix actuel » est accepté comme « entité avec le prix actuel ».
- [ ] Le lendemain, le coût d'une heure en heures pleines et d'une heure en heures
  creuses est égal à la consommation de l'heure multipliée par le prix de la période.

### Robustesse

- [ ] Après un redémarrage de Home Assistant, les prix et les couleurs Tempo
  s'affichent tout de suite.
- [ ] Redémarrage sans accès à Internet (optionnel) : les prix restent disponibles
  grâce à la grille enregistrée, les couleurs connues restent affichées ; au retour
  du réseau, tout reprend sans intervention.
- [ ] Le journal ne contient ni erreur ni avertissement de `trve_edf`, sauf pendant
  la panne d'une source, signalée une seule fois. Tout autre message est à signaler.
- [ ] La grille est retéléchargée chaque jour (diagnostics : `grid.downloaded_at`).

### Fonctions de la 0.3.0

- [ ] « Reconfigurer » change l'option ou la puissance d'un contrat ; les capteurs de
  l'ancienne option disparaissent et le nom donné au contrat est conservé.
- [ ] Les options d'un contrat Base ou Tempo affichent qu'il n'a pas d'options.
- [ ] Les diagnostics se téléchargent et ne contiennent aucune donnée personnelle (le
  nom du contrat est masqué).

## Hors recette

Ces cas ne se produisent pas forcément pendant la recette ; ils sont couverts par les
tests automatiques :

- le changement de grille tarifaire (nouvelle ligne de la CRE, appliquée à minuit) ;
- les changements d'heure (fin mars et fin octobre) ;
- la notification de réparation quand une puissance n'a plus de tarif en vigueur ;
- la source Tempo de secours.

## Critère de publication

La 1.0.0 est publiée quand toutes les vérifications passent sur plusieurs jours
consécutifs, dont au moins un changement de couleur Tempo.

## En cas d'écart

Ouvrir une issue GitHub avec :

- les diagnostics du contrat (menu ⋮ → « Télécharger les diagnostics ») ;
- la valeur attendue et sa source (ligne de la grille CRE, couleur publiée) ;
- une capture de l'historique du capteur et les lignes du journal filtrées sur
  `trve_edf`.
