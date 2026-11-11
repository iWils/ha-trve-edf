# Cahier des charges — ha-trve-edf

> Statut : **brouillon à valider** · Version du document : 0.1 · 11 novembre 2026
>
> Ce document décrit ce que fait l'intégration et comment elle est conçue. Il fait
> référence pour tout développement, humain ou assisté par IA. Toute évolution du
> périmètre passe par une modification de ce document.

## 1. Objet

`ha-trve-edf` est une intégration Home Assistant qui fournit, pour un contrat
résidentiel aux **tarifs réglementés de vente d'électricité (TRVE)** d'EDF :

- le **prix du kWh en vigueur à chaque instant**, utilisable directement dans le
  tableau de bord Énergie de Home Assistant ;
- les prix de chaque période tarifaire et le montant de l'abonnement ;
- pour l'option Tempo, la couleur des jours (bleu, blanc, rouge).

Elle sert à suivre le coût réel de sa consommation et à piloter des automatisations
(décaler un appareil en heures creuses, éviter les jours rouges…).

## 2. Principes directeurs

1. **Données publiques et officielles.** Prix publiés par la CRE en open data,
   couleurs Tempo publiées par RTE. Aucun compte, aucune clé, aucune donnée
   personnelle envoyée.
2. **Exactitude d'abord.** Un prix faux est pire qu'un prix absent : en cas de doute
   (couleur inconnue, grille introuvable), l'entité devient indisponible plutôt que
   d'afficher une valeur fausse.
3. **Sobriété.** Aussi peu de requêtes réseau que possible, et des mises à jour
   calées sur les vrais changements de période plutôt qu'un sondage permanent.
4. **Neutralité.** Projet communautaire non commercial, non affilié à EDF, à la CRE,
   à RTE ni à Home Assistant.
5. **Code neuf.** Le code est écrit à partir de ce document (voir section 11), sous
   licence GPL-3.0.

## 3. Périmètre

### 3.1 Inclus dans la version 1.0

- Les trois options TRVE résidentielles publiées par la CRE : **Base**,
  **Heures pleines / Heures creuses (HP/HC)** et **Tempo**.
- Toutes les puissances souscrites réellement proposées pour chaque option, lues
  dans les données (aujourd'hui de 3 à 36 kVA selon l'option).
- Plusieurs contrats en parallèle (plusieurs logements).

### 3.2 Les « différents contrats EDF »

| Contrat | Statut | Données officielles ouvertes | Décision proposée |
|---|---|---|---|
| Base, HP/HC, Tempo | TRVE ouverts | Oui (CRE) | **1.0** |
| EJP | TRVE fermé aux nouveaux clients depuis 1998, encore actif pour certains | Jours EJP oui (calendrier EDF, redistribué par jourtempo.fr), prix **non** publiés par la CRE | Après 1.0, si une source de prix fiable existe |
| Tarif Bleu des professionnels | TRVE non résidentiel | Non trouvées en open data | Hors périmètre pour l'instant |
| Offres de marché EDF (Zen Week-End, Zen Flex, Vert Électrique…) | Pas des tarifs réglementés | Non (prix seulement sur le site commercial d'EDF) | **Hors périmètre** : contraire au nom et au principe 1 |

L'architecture (section 7) isole chaque option tarifaire, pour pouvoir en ajouter
une sans toucher au reste.

### 3.3 Exclu de la version 1.0

- La lecture de la consommation (compteur Linky) : d'autres intégrations le font,
  et Home Assistant combine déjà prix et consommation.
- Le calcul du coût, les prévisions de couleur Tempo, les conseils de consommation :
  pistes pour après la 1.0.

## 4. Sources de données

### 4.1 Grilles tarifaires TRVE (CRE)

- Jeu de données data.gouv.fr « Historique des tarifs réglementés de vente
  d'électricité pour les consommateurs résidentiels », publié par la CRE
  (identifiant `5d31900f8b4c41338237ac8f`), licence ouverte.
- Un fichier CSV par option, séparateur `;`, accessible par une URL data.gouv
  stable qui redirige vers le site de la CRE :

  | Option | Ressource data.gouv |
  |---|---|
  | Base | `c13d05e5-9e55-4d03-bf7e-042a2ade7e49` |
  | HP/HC | `f7303b3a-93c7-4242-813d-84919034c416` |
  | Tempo | `0c3d1d36-c412-4620-8566-e5cbb4fa2b5a` |

- Colonnes communes : `DATE_DEBUT`, `DATE_FIN`, `P_SOUSCRITE`, `PART_FIXE_HT`,
  `PART_FIXE_TTC` (abonnement, en €/an). Puis, en €/kWh :
  - Base : `PART_VARIABLE_HT`, `PART_VARIABLE_TTC` ;
  - HP/HC : `PART_VARIABLE_HC_*`, `PART_VARIABLE_HP_*` ;
  - Tempo : `PART_VARIABLE_{HC|HP}{Bleu|Blanc|Rouge}_*`.
- Les colonnes sont lues **par leur nom** (ligne d'en-tête), jamais par leur
  position. Seuls les montants **TTC** sont exposés.
- La ligne applicable est celle dont la période de validité contient la date du
  jour : `DATE_DEBUT` ≤ aujourd'hui et (`DATE_FIN` vide ou ≥ aujourd'hui). Une grille
  publiée à l'avance s'applique donc toute seule le jour venu.
- **À vérifier sur le fichier brut** lors du développement : format des dates
  (probablement `JJ/MM/AAAA`), séparateur décimal, encodage. La notice de la CRE
  est jointe au jeu de données.

### 4.2 Couleurs Tempo

La source officielle est l'API « Tempo Like Supply Contract » de RTE, mais elle
exige un compte : elle n'est pas utilisable sans configuration. Proposition :

- **Source principale : API Jour Tempo** (`https://jourtempo.fr/api/v1/`),
  référencée sur data.gouv.fr, gratuite, sans clé, licence ouverte. Elle
  redistribue les couleurs publiées par RTE (`tempo.json` : aujourd'hui et demain ;
  `tempo-historique.csv` : historique depuis 2014).
- **Source de secours** : une seconde API communautaire sans clé (par exemple
  api-couleur-tempo.fr), interrogée seulement si la principale échoue.
- **Plus tard, en option** : l'API officielle RTE avec les identifiants de
  l'utilisateur.

Ces services sont jeunes et communautaires : le code les isole derrière une même
interface, pour pouvoir en changer facilement. Le format exact des réponses sera
vérifié lors du développement.

## 5. Règles métier

- **Heure de référence** : toutes les règles utilisent l'heure légale française
  (`Europe/Paris`), quel que soit le fuseau du système.
- **HP/HC** : les heures creuses sont celles du contrat (fixées par Enedis pour
  chaque logement), saisies par l'utilisateur sous forme de plages `HH:MM-HH:MM`.
  Une plage peut passer minuit. Une heure est creuse si elle appartient à une plage
  (début inclus, fin exclue).
- **Tempo** :
  - une journée Tempo va de **6 h à 6 h** le lendemain : avant 6 h, c'est la
    couleur de la veille qui s'applique ;
  - les heures creuses Tempo sont fixées nationalement de **22 h à 6 h** ;
  - la couleur du lendemain est publiée la veille, vers 10 h 40 - 11 h ; avant
    cela, elle est « inconnue » ;
  - si la couleur de la journée Tempo en cours est inconnue, le prix actuel est
    **indisponible** (principe 2).
- **Abonnement** : montant annuel TTC de la grille.

## 6. Fonctionnement dans Home Assistant

### 6.1 Configuration

1. Choix de l'option : Base, HP/HC ou Tempo.
2. Choix de la puissance, **parmi celles réellement en vigueur** pour cette option
   (liste lue dans la grille au moment de la configuration).
3. Option HP/HC uniquement : saisie des plages d'heures creuses, avec un contrôle
   strict du format et des messages d'erreur clairs.

Après coup : les plages d'heures creuses se modifient dans les **options** ; l'option
et la puissance se changent par une **reconfiguration**, sans supprimer l'intégration.

### 6.2 Appareil et entités

Un appareil (de type service) par contrat, par exemple « Tarifs réglementés EDF –
Tempo 9 kVA ». Noms d'entités traduits (français et anglais), identifiants stables
fondés sur l'entrée de configuration.

| Entité | Type | Unité | Options |
|---|---|---|---|
| Prix actuel | capteur | €/kWh | toutes |
| Période tarifaire actuelle (base / heures pleines / heures creuses) | capteur à états | — | toutes |
| Prochain changement de prix (proposé) | horodatage | — | HP/HC, Tempo |
| Abonnement | capteur | €/an | toutes |
| Prix Base | capteur | €/kWh | Base |
| Prix heures pleines, prix heures creuses | capteurs | €/kWh | HP/HC |
| Prix bleu, blanc, rouge × heures pleines, heures creuses (6) | capteurs | €/kWh | Tempo |
| Couleur Tempo en cours (journée de 6 h à 6 h) | capteur à états | — | Tempo |
| Couleur Tempo d'hier, d'aujourd'hui, de demain | capteurs à états (dont « inconnue ») | — | Tempo |

### 6.3 Mises à jour

- **Grille tarifaire** : au démarrage, puis une fois par jour.
- **Couleurs Tempo** : au démarrage, au changement de jour, puis à partir de
  l'heure de publication, à intervalle espacé, jusqu'à obtenir la couleur du
  lendemain. Une couleur connue n'est plus jamais redemandée.
- **Prix et période actuels** : recalculés **exactement** à chaque changement
  (début ou fin d'heures creuses, 6 h pour Tempo, minuit), sans sondage minute par
  minute.

### 6.4 Erreurs et disponibilité

- Délais d'attente sur toutes les requêtes ; une réponse invalide n'est jamais
  conservée.
- En cas de panne passagère, les dernières données valides restent utilisées.
- Si la puissance configurée disparaît de la grille, l'intégration le signale
  clairement (notification de réparation) au lieu d'échouer en boucle.
- Téléchargement des diagnostics possible depuis l'interface.

## 7. Architecture technique

```
custom_components/trve_edf/
├── __init__.py        # mise en place et déchargement, données de l'entrée
├── manifest.json      # domain trve_edf, type service, interrogation cloud
├── const.py
├── models.py          # options, couleurs, grilles et jours Tempo (dataclasses)
├── pricing.py         # règles métier pures, sans dépendance à Home Assistant
├── api.py             # clients CRE et Tempo (session HTTP de Home Assistant)
├── coordinator.py     # récupération et cache des données distantes
├── config_flow.py     # configuration, options, reconfiguration
├── entity.py, sensor.py
├── diagnostics.py
├── icons.json, strings.json, translations/ (en, fr)
└── brand/icon.png
```

- `pricing.py` ne dépend pas de Home Assistant : période en cours, prix actuel,
  prochain changement, journée Tempo. C'est le cœur métier, testé de façon
  exhaustive.
- Les accès réseau sont concentrés dans `api.py`, ce qui permet de changer de
  source sans toucher au reste.
- Les entités sont décrites de façon déclarative (une description par entité).
- Version minimale de Home Assistant : **2025.1** (à confirmer).

## 8. Qualité et outillage

- Objectif sur la grille de qualité des intégrations Home Assistant (Integration
  Quality Scale) : niveau **Bronze** pendant les versions 0.x, **Silver** pour la 1.0.
- Tests : logique métier couverte à 100 %, intégration testée avec
  `pytest-homeassistant-custom-component`, couverture globale d'au moins 90 %.
- Outils dans la CI : ruff (style), mypy (types), tests, hassfest, HACS Action.
- Versions SemVer : 0.x pendant le développement, 1.0.0 après validation réelle.
  Release automatique à chaque nouvelle version fusionnée dans `main` (version du
  `manifest.json` et section datée du `CHANGELOG.md`).

## 9. Feuille de route

| Version | Contenu |
|---|---|
| socle | CI, release automatique, squelette de l'intégration, outillage de tests |
| 0.1.0 | Base et HP/HC : configuration, prix, période, abonnement |
| 0.2.0 | Tempo : couleurs, prix du jour Tempo, sources principale et de secours |
| 0.3.0 | Qualité : reconfiguration, diagnostics, réparations, icônes |
| 1.0.0 | Validation réelle côte à côte avec l'ancienne intégration, documentation |

## 10. Migration depuis l'intégration `tarif_edf`

Le domain est différent (`trve_edf`) : les deux intégrations peuvent fonctionner
côte à côte, ce qui permet de comparer les prix avant de basculer. Il n'y a pas de
migration automatique. La procédure sera documentée : installer et configurer
`ha-trve-edf`, choisir son capteur « Prix actuel » dans le tableau de bord Énergie,
adapter les automatisations, puis supprimer l'ancienne intégration.

## 11. Conception propre

Pour garantir un code neuf, sans reprise du projet `hass-tarif-edf` :

- aucun code de `delphiki/hass-tarif-edf` ni de `iWils/hass-tarif-edf` n'est copié
  ou adapté ;
- sont utilisables les **faits publics** (adresses et colonnes des données, règles
  des tarifs) et les **comportements attendus**, y compris ceux révélés par les
  bugs de l'ancienne intégration, sous forme de cas de test ;
- le code est écrit à partir de ce cahier des charges.

## 12. Questions ouvertes

1. Confirmer le périmètre 1.0 : Base, HP/HC et Tempo ; EJP plus tard ; offres de
   marché hors périmètre.
2. Valider les sources Tempo : Jour Tempo en principal, une autre API communautaire
   en secours.
3. Abonnement exprimé en €/an (valeur officielle) ou converti en €/mois ?
4. Garder l'entité « Prochain changement de prix » ?
5. Heures creuses Tempo fixes (22 h - 6 h), non modifiables : d'accord ?
6. Version minimale de Home Assistant 2025.1 : d'accord ?
