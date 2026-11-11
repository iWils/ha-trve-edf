"""Tests of the setup of the integration."""

from __future__ import annotations

from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.trve_edf.api import CreConnectionError
from custom_components.trve_edf.const import (
    CONF_OFF_PEAK_HOURS,
    CONF_OPTION,
    CONF_POWER,
    DOMAIN,
)
from custom_components.trve_edf.models import OffPeakRange, TariffOption

from .common import COORDINATOR_FETCH, HPHC_GRID, paris, setup_contract


async def test_setup_and_unload_entry(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A contract is set up, then unloaded with its clock stopped."""
    freezer.move_to(paris(2026, 11, 11, 12, 0))
    entry = await setup_contract(hass, TariffOption.BASE)
    assert entry.state is ConfigEntryState.LOADED
    coordinator = entry.runtime_data

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    unloaded = hass.config_entries.async_get_entry(entry.entry_id)
    assert unloaded is not None
    assert unloaded.state is ConfigEntryState.NOT_LOADED
    assert coordinator._unsub_clock is None


async def test_setup_retried_when_the_grid_cannot_be_downloaded(
    hass: HomeAssistant,
) -> None:
    """Without a first grid, the setup is retried later."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Base 6 kVA",
        data={CONF_OPTION: "base", CONF_POWER: 6},
    )
    entry.add_to_hass(hass)
    with patch(COORDINATOR_FETCH, side_effect=CreConnectionError("offline")):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_options_update_reloads_the_entry(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """New off-peak hours are applied by reloading the contract."""
    freezer.move_to(paris(2026, 11, 11, 12, 0))
    entry = await setup_contract(hass, TariffOption.HPHC, off_peak="22:00-06:00")

    with patch(COORDINATOR_FETCH, return_value=HPHC_GRID):
        hass.config_entries.async_update_entry(
            entry, options={CONF_OFF_PEAK_HOURS: "01:00-07:00"}
        )
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.off_peak == (
        OffPeakRange(
            start=paris(2026, 1, 1, 1, 0).time(), end=paris(2026, 1, 1, 7, 0).time()
        ),
    )
