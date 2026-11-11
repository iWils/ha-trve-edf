"""The EDF regulated tariffs (TRVE) integration.

This is the scaffold of the integration: setting up an entry does nothing yet.
The data sources, the tariff rules and the entities come in the next versions,
as described in docs/cahier-des-charges.md.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a TRVE contract from a config entry."""
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return True
