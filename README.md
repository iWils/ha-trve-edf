# Tarifs réglementés EDF (TRVE) pour Home Assistant

🇬🇧 [English version](README.en.md)

> 🚧 **En développement (0.x)** : les options Base, Heures pleines / Heures creuses
> et Tempo sont disponibles depuis la 0.2.0. La 1.0 viendra après validation en
> conditions réelles.

Intégration Home Assistant qui fournit les **tarifs réglementés de vente d'électricité
(TRVE)** d'EDF correspondant à votre contrat, et le **prix du kWh en vigueur à chaque
instant**, à partir des données publiques officielles.

## Fonctions prévues (version 1.0)

- Options **Base**, **Heures pleines / Heures creuses** et **Tempo**, pour toutes les
  puissances réellement proposées.
- Prix actuel du kWh, directement utilisable dans le tableau de bord Énergie.
- Période tarifaire en cours, prix de chaque période et abonnement.
- Tempo : couleur de la journée en cours, d'hier, d'aujourd'hui et de demain.
- Calcul à l'heure française, quel que soit le fuseau du système, et mise à jour
  exactement à chaque changement de période.

Le détail est dans le [cahier des charges](docs/cahier-des-charges.md).

## Sources de données

- Prix : jeu de données de la **Commission de régulation de l'énergie (CRE)** sur
  data.gouv.fr, « Historique des tarifs réglementés de vente d'électricité pour les
  consommateurs résidentiels ».
- Couleurs Tempo : publiées par **RTE**, via une API ouverte sans clé.

Aucun compte n'est nécessaire et aucune donnée personnelle n'est envoyée.

## Installation

Home Assistant 2025.1 ou plus récent est nécessaire.

1. Dans HACS, ajoutez `https://github.com/iWils/ha-trve-edf` comme dépôt personnalisé
   de type « Intégration ».
2. Installez « Tarifs réglementés EDF (TRVE) », puis redémarrez Home Assistant.
3. Dans Paramètres → Appareils et services, ajoutez l'intégration « Tarifs réglementés
   EDF (TRVE) ».

## Configuration

1. Choisissez l'option de votre contrat : Base, Heures pleines / Heures creuses ou
   Tempo.
2. Choisissez votre puissance souscrite : seules les puissances actuellement
   proposées pour cette option sont listées.
3. Heures pleines / Heures creuses : saisissez vos heures creuses telles qu'indiquées
   sur votre facture, par exemple `22:00-06:00` ou `01:30-07:30,12:30-14:30`. Elles se
   modifient ensuite dans les options de l'intégration. Pour Tempo, les heures creuses
   sont fixées nationalement de 22 h à 6 h : rien à saisir.

Plusieurs contrats peuvent être ajoutés, par exemple pour plusieurs logements.

Pour changer d'option ou de puissance, inutile de supprimer l'intégration : dans
Paramètres → Appareils et services → Tarifs réglementés EDF (TRVE), ouvrez le menu
⋮ du contrat et choisissez « Reconfigurer ». Les capteurs de l'ancienne option sont
alors retirés, et le nom que vous avez donné au contrat est conservé.

## Entités

| Entité | Options | Description |
|---|---|---|
| Prix actuel | toutes | Prix du kWh en vigueur, en €/kWh TTC |
| Période tarifaire actuelle | toutes | Base, heures pleines ou heures creuses |
| Abonnement annuel | toutes | Montant annuel TTC, en € |
| Prix Base | Base | Prix du kWh, en €/kWh TTC |
| Prix heures pleines, prix heures creuses | HP/HC | Prix du kWh de chaque période |
| Prix bleu, blanc, rouge × heures pleines, heures creuses | Tempo | Les 6 prix du kWh Tempo |
| Prochain changement de prix | HP/HC, Tempo | Date et heure du prochain changement : passage HP/HC, ou nouvelle grille tarifaire à minuit |
| Couleur Tempo en cours | Tempo | Couleur de la journée Tempo en cours, de 6 h à 6 h le lendemain |
| Couleur Tempo d'hier, d'aujourd'hui, de demain | Tempo | Celle de demain reste « Inconnu » tant qu'elle n'est pas publiée (vers 11 h) ; hier et aujourd'hui sont indisponibles si leur couleur manque |

Pour le tableau de bord Énergie, choisissez « Utiliser une entité avec le prix
actuel » et sélectionnez le capteur « Prix actuel ».

Les prix sont recalculés à l'instant exact de chaque changement de période, à l'heure
française. La grille tarifaire est téléchargée une fois par jour et enregistrée. Si elle ne peut
plus être téléchargée, la dernière grille connue reste utilisée, y compris après un
redémarrage, pendant 7 jours au plus après son téléchargement : les prix deviennent
ensuite indisponibles plutôt que d'afficher une valeur peut-être fausse. De même,
pour Tempo, le prix actuel est indisponible tant que la couleur de la journée en
cours n'est pas connue.

Les couleurs Tempo viennent de Jour Tempo, qui redistribue les données de RTE, avec
une source de secours. Elles sont demandées seulement quand il en manque une
(celle de demain, à partir de 10 h 30), enregistrées et partagées par tous les
contrats Tempo.

## En cas de problème

- Si votre puissance souscrite n'a plus de tarif en vigueur dans la grille de la CRE,
  une notification apparaît dans Paramètres → Réparations : reconfigurez alors le
  contrat.
- Les diagnostics du contrat (menu ⋮ → « Télécharger les diagnostics ») montrent la
  grille utilisée, le tarif en vigueur, la période et le prix calculés, et les
  couleurs Tempo connues. Ils ne contiennent aucune donnée personnelle (le nom du
  contrat y est masqué) : joignez-les à une issue GitHub pour signaler un prix faux.

## Développement

Le projet est développé avec l'aide de l'IA, dans le cadre fixé par le
[cahier des charges](docs/cahier-des-charges.md) et les règles de
[`CLAUDE.md`](CLAUDE.md), qui donne aussi les commandes de test. Chaque modification
passe par une pull request vérifiée par la CI : style, types, tests, hassfest et HACS.

Les versions suivent [SemVer](https://semver.org) (0.x pendant le développement). Une
release est publiée automatiquement à chaque nouvelle version fusionnée dans `main` ;
l'historique est dans le [changelog](CHANGELOG.md).

## Licence et avertissement

Distribué sous licence [GPL-3.0](LICENSE). Projet communautaire et non commercial,
non affilié à EDF, à la CRE, à RTE ni à Home Assistant.
