"""The EDF regulated tariffs (TRVE) integration."""

from __future__ import annotations

from functools import partial

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .coordinator import TrveEdfConfigEntry, TrveEdfCoordinator
from .models import TariffOption
from .tempo import async_acquire_tempo_colors, async_release_tempo_colors

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: TrveEdfConfigEntry) -> bool:
    """Set up a TRVE contract from a config entry."""
    coordinator = TrveEdfCoordinator(hass, entry)
    if coordinator.option is TariffOption.TEMPO:
        tempo = await async_acquire_tempo_colors(hass)
        entry.async_on_unload(partial(async_release_tempo_colors, hass, tempo))
        coordinator.async_attach_tempo(tempo)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    coordinator.async_start_clock()
    entry.async_on_unload(coordinator.async_stop_clock)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TrveEdfConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: TrveEdfConfigEntry) -> None:
    """Remove the repair issues of a deleted contract."""
    ir.async_delete_issue(hass, DOMAIN, f"power_not_available_{entry.entry_id}")


async def _async_update_listener(
    hass: HomeAssistant, entry: TrveEdfConfigEntry
) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
