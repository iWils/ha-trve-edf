"""Tests of the sensors."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.trve_edf.api import CreConnectionError
from custom_components.trve_edf.const import DOMAIN
from custom_components.trve_edf.models import TariffOption

from .common import (
    COORDINATOR_FETCH,
    HPHC_GRID,
    entity_id,
    paris,
    setup_contract,
    state,
)


async def _at(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, when: datetime
) -> None:
    """Move the clock to a moment and let scheduled callbacks run."""
    freezer.move_to(when)
    async_fire_time_changed(hass, when)
    await hass.async_block_till_done()


async def test_base_sensors(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A Base contract exposes its single price, period and subscription."""
    freezer.move_to(paris(2026, 11, 11, 12, 0))
    entry = await setup_contract(hass, TariffOption.BASE)

    assert state(hass, entry, "current_price").state == "0.2001"
    assert (
        state(hass, entry, "current_price").attributes["unit_of_measurement"]
        == "EUR/kWh"
    )
    assert state(hass, entry, "base_price").state == "0.2001"
    assert state(hass, entry, "subscription").state == "190.81"
    assert state(hass, entry, "current_period").state == "base"
    assert state(hass, entry, "current_period").attributes["options"] == ["base"]
    for key in ("next_price_change", "peak_price", "off_peak_price"):
        assert entity_id(hass, entry, key) is None


async def test_hphc_sensors_follow_off_peak_hours(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The current price switches exactly at the off-peak boundaries."""
    freezer.move_to(paris(2026, 11, 11, 21, 30))
    entry = await setup_contract(hass, TariffOption.HPHC, off_peak="22:00-06:00")

    assert state(hass, entry, "current_price").state == "0.2142"
    assert state(hass, entry, "current_period").state == "peak"
    assert state(hass, entry, "next_price_change").state == "2026-11-11T21:00:00+00:00"
    assert state(hass, entry, "peak_price").state == "0.2142"
    assert state(hass, entry, "off_peak_price").state == "0.1589"
    assert state(hass, entry, "current_period").attributes["options"] == [
        "peak",
        "off_peak",
    ]

    await _at(hass, freezer, paris(2026, 11, 11, 22, 0))

    assert state(hass, entry, "current_price").state == "0.1589"
    assert state(hass, entry, "current_period").state == "off_peak"
    assert state(hass, entry, "next_price_change").state == "2026-11-12T05:00:00+00:00"

    await _at(hass, freezer, paris(2026, 11, 12, 6, 0))

    assert state(hass, entry, "current_price").state == "0.2142"
    assert state(hass, entry, "current_period").state == "peak"


async def test_prices_follow_the_validity_dates(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """At midnight, the row of the new tariff period applies by itself."""
    freezer.move_to(paris(2026, 7, 31, 23, 30))
    entry = await setup_contract(hass, TariffOption.BASE)
    assert state(hass, entry, "current_price").state == "0.194"
    assert state(hass, entry, "subscription").state == "188.2"

    await _at(hass, freezer, paris(2026, 8, 1, 0, 0))

    assert state(hass, entry, "current_price").state == "0.2001"
    assert state(hass, entry, "subscription").state == "190.81"


async def test_prices_unavailable_without_row_for_the_power(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Without a row for the subscribed power, prices are unavailable."""
    freezer.move_to(paris(2026, 11, 11, 12, 0))
    entry = await setup_contract(hass, TariffOption.BASE, power=36)

    assert state(hass, entry, "current_price").state == STATE_UNAVAILABLE
    assert state(hass, entry, "subscription").state == STATE_UNAVAILABLE
    assert state(hass, entry, "current_period").state == "base"


async def test_old_prices_are_kept_then_dropped_when_downloads_fail(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """After a failed download the last grid is used, but not beyond 7 days."""
    start = paris(2026, 11, 11, 12, 0)
    freezer.move_to(start)
    entry = await setup_contract(hass, TariffOption.HPHC, off_peak="22:00-06:00")

    with patch(COORDINATOR_FETCH, side_effect=CreConnectionError("offline")):
        await _at(hass, freezer, start + timedelta(days=1, minutes=1))
        assert state(hass, entry, "current_price").state == "0.2142"

        await _at(hass, freezer, start + timedelta(days=7, minutes=2))
        assert state(hass, entry, "current_price").state == STATE_UNAVAILABLE
        assert state(hass, entry, "peak_price").state == STATE_UNAVAILABLE
        assert state(hass, entry, "current_period").state == "peak"

    with patch(COORDINATOR_FETCH, return_value=HPHC_GRID):
        await _at(hass, freezer, start + timedelta(days=8, minutes=3))
    assert state(hass, entry, "current_price").state == "0.2142"


async def test_device_and_unique_ids(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Every sensor belongs to the service device of its contract."""
    freezer.move_to(paris(2026, 11, 11, 12, 0))
    entry = await setup_contract(hass, TariffOption.BASE)

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None
    assert device.name == entry.title
    assert device.entry_type is dr.DeviceEntryType.SERVICE
    assert entity_id(hass, entry, "current_price") is not None
