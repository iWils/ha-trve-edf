# EDF regulated tariffs (TRVE) for Home Assistant

🇫🇷 [Version française](README.md)

> 🚧 **Under development (0.x)**: the Base, Peak / Off-peak hours and Tempo options
> are available since 0.2.0. Version 1.0 will follow a validation in real
> conditions.

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

1. Choose the option of your contract: Base, Peak / Off-peak hours (HP/HC) or Tempo.
2. Choose your subscribed power: only the powers currently offered for this option
   are listed.
3. HP/HC: enter your off-peak hours as written on your bill, for example
   `22:00-06:00` or `01:30-07:30,12:30-14:30`. They can be changed later in the
   options of the integration. Tempo off-peak hours are set nationally, from 22:00 to
   06:00: nothing to enter.

Several contracts can be added, for example for several homes.

To change the option or the power, there is no need to remove the integration: in
Settings → Devices & services → Tarifs réglementés EDF (TRVE), open the ⋮ menu of
the contract and choose "Reconfigure". The sensors of the former option are then
removed, and the name you gave to the contract is kept.

## Entities

| Entity | Options | Description |
|---|---|---|
| Current price | all | Price of the kWh in force, in EUR/kWh including taxes |
| Current tariff period | all | Base, peak hours or off-peak hours |
| Yearly subscription | all | Yearly amount including taxes, in EUR |
| Base price | Base | Price of the kWh, in EUR/kWh including taxes |
| Peak hours price, off-peak hours price | HP/HC | Price of the kWh of each period |
| Blue, white, red × peak, off-peak hours prices | Tempo | The 6 Tempo prices of the kWh |
| Next price change | HP/HC, Tempo | Date and time of the next change: peak/off-peak switch, or new tariff grid at midnight |
| Current Tempo color | Tempo | Color of the current Tempo day, from 06:00 to 06:00 the next day |
| Yesterday's, today's, tomorrow's Tempo color | Tempo | Tomorrow's stays "Unknown" until published (around 11:00); yesterday's and today's are unavailable if missing |

For the Energy dashboard, choose "Use an entity with current price" and select the
"Current price" sensor.

Prices are recomputed at the exact moment of each period change, in French time. The
tariff grid is downloaded once a day and saved. If it cannot be downloaded anymore,
the last known grid is still used, even after a restart, for 7 days at most after its
download: prices then become unavailable rather than showing a possibly wrong value.
Likewise, for Tempo, the current price is unavailable until the color of the current
Tempo day is known.

Tempo colors come from Jour Tempo, which redistributes the RTE data, with a fallback
source. They are only asked for when one is missing (tomorrow's, from 10:30), saved
and shared by all the Tempo contracts.

## Troubleshooting

- If your subscribed power has no tariff in force in the CRE grid anymore, a
  notification appears in Settings → Repairs: reconfigure the contract.
- The diagnostics of the contract (⋮ menu → "Download diagnostics") show the grid in
  use, the tariff in force, the computed period and price, and the known Tempo
  colors. They hold no personal data (the name of the contract is redacted): attach
  them to a GitHub issue to report a wrong price.

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
