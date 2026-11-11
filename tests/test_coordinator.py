"""Tests of the coordinator: saved grid and price changes."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.trve_edf.api import CreConnectionError
from custom_components.trve_edf.const import CONF_OPTION, CONF_POWER, DOMAIN
from custom_components.trve_edf.models import TariffOption, grid_to_dict

from .common import (
    BASE_GRID,
    COORDINATOR_FETCH,
    HPHC_GRID,
    paris,
    setup_contract,
    state,
)

STORAGE_KEY = f"{DOMAIN}.grid_base"


def saved_grid(downloaded_at: datetime, grid: Any = None) -> dict[str, Any]:
    """Return the storage content of a saved Base grid."""
    return {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {
            "downloaded_at": downloaded_at.isoformat(),
            "grid": grid_to_dict(BASE_GRID) if grid is None else grid,
        },
    }


async def add_base_contract(hass: HomeAssistant) -> MockConfigEntry:
    """Add a Base contract without setting it up."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Base 6 kVA", data={CONF_OPTION: "base", CONF_POWER: 6}
    )
    entry.add_to_hass(hass)
    return entry


async def test_downloaded_grid_is_saved(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """A downloaded grid is saved with its download time."""
    freezer.move_to(paris(2026, 11, 11, 12, 0))
    await setup_contract(hass, TariffOption.BASE)

    saved = hass_storage[STORAGE_KEY]["data"]
    assert saved["grid"] == grid_to_dict(BASE_GRID)
    assert saved["downloaded_at"] == "2026-11-11T11:00:00+00:00"


async def test_recent_saved_grid_is_reused_without_download(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """A grid saved less than a day ago is reused, even by another contract."""
    freezer.move_to(paris(2026, 11, 11, 12, 0))
    hass_storage[STORAGE_KEY] = saved_grid(paris(2026, 11, 10, 18, 0))
    entry = await add_base_contract(hass)

    fetch = AsyncMock(side_effect=AssertionError("no download expected"))
    with patch(COORDINATOR_FETCH, fetch):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    fetch.assert_not_awaited()
    assert state(hass, entry, "current_price").state == "0.2001"


async def test_saved_grid_used_when_the_cre_cannot_be_reached(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """After a restart without network, a saved grid under 7 days is used."""
    freezer.move_to(paris(2026, 11, 11, 12, 0))
    hass_storage[STORAGE_KEY] = saved_grid(paris(2026, 11, 8, 12, 0))
    entry = await add_base_contract(hass)

    with patch(COORDINATOR_FETCH, side_effect=CreConnectionError("offline")):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert state(hass, entry, "current_price").state == "0.2001"

    # The grid is trusted until 7 days after its download, not after the restart.
    with patch(COORDINATOR_FETCH, side_effect=CreConnectionError("offline")):
        expiry = paris(2026, 11, 15, 12, 0)
        freezer.move_to(expiry)
        async_fire_time_changed(hass, expiry)
        await hass.async_block_till_done()
    assert state(hass, entry, "current_price").state == STATE_UNAVAILABLE


async def test_old_saved_grid_is_not_used(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """A saved grid of 7 days or more is not used: the setup is retried."""
    freezer.move_to(paris(2026, 11, 11, 12, 0))
    hass_storage[STORAGE_KEY] = saved_grid(paris(2026, 11, 4, 12, 0))
    entry = await add_base_contract(hass)

    with patch(COORDINATOR_FETCH, side_effect=CreConnectionError("offline")):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_invalid_saved_grid_is_ignored(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """A broken or foreign saved grid is ignored and replaced by a download."""
    freezer.move_to(paris(2026, 11, 11, 12, 0))
    hass_storage[STORAGE_KEY] = saved_grid(
        paris(2026, 11, 11, 11, 0), grid=grid_to_dict(HPHC_GRID)
    )
    entry = await add_base_contract(hass)

    with patch(COORDINATOR_FETCH, return_value=BASE_GRID) as fetch:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    fetch.assert_awaited_once()
    assert hass_storage[STORAGE_KEY]["data"]["grid"] == grid_to_dict(BASE_GRID)


async def test_unreadable_storage_is_ignored(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """Storage content that is not a saved grid is ignored."""
    freezer.move_to(paris(2026, 11, 11, 12, 0))
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": ["not", "a", "grid"],
    }
    entry = await add_base_contract(hass)

    with patch(COORDINATOR_FETCH, return_value=BASE_GRID) as fetch:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    fetch.assert_awaited_once()


async def test_next_price_change_includes_a_new_grid_row_at_midnight(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The next price change is midnight when a new row brings another price."""
    freezer.move_to(paris(2026, 7, 31, 21, 0))
    entry = await setup_contract(hass, TariffOption.HPHC, off_peak="22:00-06:00")
    coordinator = entry.runtime_data

    # Before 22:00, the period change comes first.
    assert coordinator.next_price_change(paris(2026, 7, 31, 21, 0)) == paris(
        2026, 7, 31, 22, 0
    )
    # In the off-peak hours, the new row of 1 August changes the price at midnight.
    assert coordinator.next_price_change(paris(2026, 7, 31, 23, 0)) == paris(
        2026, 8, 1, 0, 0
    )
    # Afterwards, the next change is the end of the off-peak hours.
    assert coordinator.next_price_change(paris(2026, 8, 1, 0, 0)) == paris(
        2026, 8, 1, 6, 0
    )
    # A midnight without new row is not a price change.
    assert coordinator.next_price_change(paris(2026, 11, 11, 23, 0)) == paris(
        2026, 11, 12, 6, 0
    )


async def test_next_price_change_ignores_rows_of_an_untrusted_grid(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Without a trusted grid, only the period changes are known."""
    freezer.move_to(paris(2026, 7, 31, 21, 0))
    entry = await setup_contract(hass, TariffOption.HPHC, off_peak="22:00-06:00")
    coordinator = entry.runtime_data
    coordinator.grid_downloaded_at = paris(2026, 7, 20, 12, 0)

    assert coordinator.next_price_change(paris(2026, 7, 31, 23, 0)) == paris(
        2026, 8, 1, 6, 0
    )


async def test_clock_survives_a_failing_listener(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The next tick is scheduled before notifying, so an error cannot stop it."""
    freezer.move_to(paris(2026, 11, 11, 21, 30))
    entry = await setup_contract(hass, TariffOption.HPHC, off_peak="22:00-06:00")
    coordinator = entry.runtime_data
    coordinator.async_stop_clock()

    boundary = paris(2026, 11, 11, 22, 0)
    freezer.move_to(boundary)
    with (
        patch.object(
            coordinator, "async_update_listeners", side_effect=RuntimeError("boom")
        ),
        pytest.raises(RuntimeError),
    ):
        coordinator._async_tick(boundary)

    assert coordinator._unsub_clock is not None
    later = boundary + timedelta(hours=8)
    freezer.move_to(later)
    async_fire_time_changed(hass, later)
    await hass.async_block_till_done()
    assert state(hass, entry, "current_period").state == "peak"
