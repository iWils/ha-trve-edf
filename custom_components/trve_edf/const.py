"""Constants of the EDF regulated tariffs (TRVE) integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "trve_edf"

CONF_OPTION: Final = "option"
CONF_POWER: Final = "power_kva"
CONF_OFF_PEAK_HOURS: Final = "off_peak_hours"

GRID_REFRESH_INTERVAL: Final = timedelta(days=1)
"""How often the tariff grid is downloaded again."""

GRID_MAX_AGE: Final = timedelta(days=7)
"""Beyond this age without a successful download, prices are not trusted anymore."""

TITLE_PREFIX: Final = "Tarifs réglementés EDF"
TITLE_SEPARATOR: Final = " \u2013 "
"""En dash between the prefix and the contract in the title of an entry."""
