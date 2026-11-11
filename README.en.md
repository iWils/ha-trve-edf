# EDF regulated tariffs (TRVE) for Home Assistant

🇫🇷 [Version française](README.md)

> 🚧 **Under development (0.x)**: no version has been released yet.

Home Assistant integration that provides the EDF **regulated electricity tariffs
(TRVE, "tarifs réglementés de vente d'électricité")** of your contract, and the
**price of the kWh in force at any time**, from official public data.

## Planned features (version 1.0)

- **Base**, **Peak / Off-peak hours (HP/HC)** and **Tempo** options, for every
  subscribed power actually offered.
- Current price of the kWh, ready for the Home Assistant Energy dashboard.
- Current tariff period, price of each period and subscription.
- Tempo: color of the current Tempo day, of yesterday, today and tomorrow.
- Computed in French time, whatever the system time zone, and updated exactly at
  each period change.

Details are in the [specification](docs/cahier-des-charges.md) (in French).

## Data sources

- Prices: dataset of the French energy regulator (**CRE**) on data.gouv.fr,
  "Historique des tarifs réglementés de vente d'électricité pour les consommateurs
  résidentiels".
- Tempo colors: published by **RTE**, through an open API without key.

No account is needed and no personal data is sent.

## Installation

Once the first version is released: in HACS, add this repository as a custom
repository of type "Integration", install "Tarifs réglementés EDF (TRVE)", restart
Home Assistant, then add the integration.

## License and disclaimer

Released under the [GPL-3.0](LICENSE) license. Community, non-commercial project,
not affiliated with EDF, the CRE, RTE or Home Assistant.
