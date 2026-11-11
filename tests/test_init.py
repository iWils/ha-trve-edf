"""Tests of the setup of the integration."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.trve_edf.const import DOMAIN


async def test_setup_and_unload_entry(hass: HomeAssistant) -> None:
    """An entry is set up, then unloaded."""
    entry = MockConfigEntry(domain=DOMAIN, title="Tempo 9 kVA")
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    unloaded = hass.config_entries.async_get_entry(entry.entry_id)
    assert unloaded is not None
    assert unloaded.state is ConfigEntryState.NOT_LOADED
