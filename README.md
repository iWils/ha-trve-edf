# Tarifs réglementés EDF (TRVE) pour Home Assistant

🇬🇧 [English version](README.en.md)

> 🚧 **En développement (0.x)** : la version 0.1.0 gère les options Base et
> Heures pleines / Heures creuses. Tempo arrive avec la 0.2.0.

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

1. Choisissez l'option de votre contrat : Base ou Heures pleines / Heures creuses.
2. Choisissez votre puissance souscrite : seules les puissances actuellement
   proposées pour cette option sont listées.
3. Heures pleines / Heures creuses : saisissez vos heures creuses telles qu'indiquées
   sur votre facture, par exemple `22:00-06:00` ou `01:30-07:30,12:30-14:30`. Elles se
   modifient ensuite dans les options de l'intégration.

Plusieurs contrats peuvent être ajoutés, par exemple pour plusieurs logements.

## Entités

| Entité | Options | Description |
|---|---|---|
| Prix actuel | toutes | Prix du kWh en vigueur, en €/kWh TTC |
| Période tarifaire actuelle | toutes | Base, heures pleines ou heures creuses |
| Abonnement annuel | toutes | Montant annuel TTC, en € |
| Prix Base | Base | Prix du kWh, en €/kWh TTC |
| Prix heures pleines, prix heures creuses | HP/HC | Prix du kWh de chaque période |
| Prochain changement de prix | HP/HC | Date et heure du prochain passage HP/HC |

Pour le tableau de bord Énergie, choisissez « Utiliser une entité avec le prix
actuel » et sélectionnez le capteur « Prix actuel ».

Les prix sont recalculés à l'instant exact de chaque changement de période, à l'heure
française. Si la grille tarifaire ne peut plus être téléchargée, les derniers prix
connus restent utilisés pendant 7 jours au plus, puis deviennent indisponibles plutôt
que d'afficher une valeur peut-être fausse.

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
