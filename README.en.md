# EDF regulated tariffs (TRVE) for Home Assistant

🇫🇷 [Version française](README.md)

> 🚧 **Under development (0.x)**: version 0.1.0 supports the Base and Peak /
> Off-peak hours options. Tempo comes with 0.2.0.

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

Home Assistant 2025.1 or newer is required.

1. In HACS, add `https://github.com/iWils/ha-trve-edf` as a custom repository of type
   "Integration".
2. Install "Tarifs réglementés EDF (TRVE)", then restart Home Assistant.
3. In Settings → Devices & services, add the "Tarifs réglementés EDF (TRVE)"
   integration.

## Configuration

1. Choose the option of your contract: Base or Peak / Off-peak hours (HP/HC).
2. Choose your subscribed power: only the powers currently offered for this option
   are listed.
3. HP/HC: enter your off-peak hours as written on your bill, for example
   `22:00-06:00` or `01:30-07:30,12:30-14:30`. They can be changed later in the
   options of the integration.

Several contracts can be added, for example for several homes.

## Entities

| Entity | Options | Description |
|---|---|---|
| Current price | all | Price of the kWh in force, in EUR/kWh including taxes |
| Current tariff period | all | Base, peak hours or off-peak hours |
| Yearly subscription | all | Yearly amount including taxes, in EUR |
| Base price | Base | Price of the kWh, in EUR/kWh including taxes |
| Peak hours price, off-peak hours price | HP/HC | Price of the kWh of each period |
| Next price change | HP/HC | Date and time of the next peak/off-peak switch |

For the Energy dashboard, choose "Use an entity with current price" and select the
"Current price" sensor.

Prices are recomputed at the exact moment of each period change, in French time. If
the tariff grid cannot be downloaded anymore, the last known prices are used for 7
days at most, then become unavailable rather than showing a possibly wrong value.

## Development

The project is developed with the help of AI, within the frame set by the
[specification](docs/cahier-des-charges.md) and the rules of
[`CLAUDE.md`](CLAUDE.md), which also lists the test commands. Every change goes
through a pull request checked by the CI: style, types, tests, hassfest and HACS.

Versions follow [SemVer](https://semver.org) (0.x during development). A release is
published automatically for each new version merged into `main`; the history is in
the [changelog](CHANGELOG.md).

## License and disclaimer

Released under the [GPL-3.0](LICENSE) license. Community, non-commercial project,
not affiliated with EDF, the CRE, RTE or Home Assistant.
