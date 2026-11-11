# Tarifs réglementés EDF (TRVE) pour Home Assistant

🇬🇧 [English version](README.en.md)

> 🚧 **En développement (0.x)** : aucune version n'est encore publiée.

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

Quand la première version sera publiée : dans HACS, ajoutez ce dépôt comme dépôt
personnalisé de type « Intégration », installez « Tarifs réglementés EDF (TRVE) »,
redémarrez Home Assistant puis ajoutez l'intégration.

## Licence et avertissement

Distribué sous licence [GPL-3.0](LICENSE). Projet communautaire et non commercial,
non affilié à EDF, à la CRE, à RTE ni à Home Assistant.
