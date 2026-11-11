"""Tests of the Tempo option: colors, prices and the shared colors coordinator."""

from __future__ import annotations

from datetime import date, datetime
import logging
from typing import Any
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.trve_edf.api import TrveEdfError
from custom_components.trve_edf.const import DOMAIN
from custom_components.trve_edf.models import TariffOption, TempoColor
from custom_components.trve_edf.tempo import DATA_TEMPO_COLORS

from .common import (
    COORDINATOR_FETCH,
    TEMPO_FETCH,
    TEMPO_GRID,
    FakeTempoSource,
    entity_id,
    paris,
    setup_contract,
    state,
)

BLUE, WHITE, RED = TempoColor.BLUE, TempoColor.WHITE, TempoColor.RED
YESTERDAY, TODAY, TOMORROW = date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 12)
COLORS_STORAGE = f"{DOMAIN}.tempo_colors"


async def _at(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    when: datetime,
    source: FakeTempoSource,
) -> None:
    """Move the clock to a moment, with the color source and the grid simulated."""
    freezer.move_to(when)
    with (
        patch(TEMPO_FETCH, source),
        patch(COORDINATOR_FETCH, return_value=TEMPO_GRID),
    ):
        async_fire_time_changed(hass, when)
        await hass.async_block_till_done()


async def test_tempo_sensors_on_a_red_day(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """On a red day in peak hours, the red peak price applies."""
    freezer.move_to(paris(2026, 11, 11, 7, 0))
    source = FakeTempoSource({YESTERDAY: WHITE, TODAY: RED})
    entry = await setup_contract(hass, TariffOption.TEMPO, tempo=source)

    assert state(hass, entry, "current_price").state == "0.7295"
    assert state(hass, entry, "current_period").state == "peak"
    assert state(hass, entry, "tempo_color").state == "red"
    assert state(hass, entry, "tempo_color").attributes["options"] == [
        "blue",
        "white",
        "red",
    ]
    assert state(hass, entry, "tempo_color_yesterday").state == "white"
    assert state(hass, entry, "tempo_color_today").state == "red"
    assert state(hass, entry, "tempo_color_tomorrow").state == STATE_UNKNOWN
    assert state(hass, entry, "next_price_change").state == "2026-11-11T21:00:00+00:00"
    assert state(hass, entry, "subscription").state == "189.9802924"
    expected_prices = {
        "blue_peak_price": "0.1654",
        "blue_off_peak_price": "0.1356",
        "white_peak_price": "0.1921",
        "white_off_peak_price": "0.1536",
        "red_peak_price": "0.7295",
        "red_off_peak_price": "0.1615",
    }
    for key, price in expected_prices.items():
        assert state(hass, entry, key).state == price, key
    for key in ("base_price", "peak_price", "off_peak_price"):
        assert entity_id(hass, entry, key) is None


async def test_before_6am_the_previous_tempo_day_applies(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Before 06:00, the color of the Tempo day started the day before applies."""
    freezer.move_to(paris(2026, 11, 11, 5, 0))
    source = FakeTempoSource({YESTERDAY: WHITE, TODAY: RED})
    entry = await setup_contract(hass, TariffOption.TEMPO, tempo=source)

    assert state(hass, entry, "tempo_color").state == "white"
    assert state(hass, entry, "current_period").state == "off_peak"
    assert state(hass, entry, "current_price").state == "0.1536"
    assert state(hass, entry, "tempo_color_today").state == "red"

    await _at(hass, freezer, paris(2026, 11, 11, 6, 0), source)

    assert state(hass, entry, "tempo_color").state == "red"
    assert state(hass, entry, "current_price").state == "0.7295"


async def test_unknown_color_makes_the_current_price_unavailable(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Without the color of the current Tempo day, the price is not shown."""
    freezer.move_to(paris(2026, 11, 11, 7, 0))
    entry = await setup_contract(hass, TariffOption.TEMPO, tempo=FakeTempoSource())

    assert state(hass, entry, "current_price").state == STATE_UNAVAILABLE
    assert state(hass, entry, "tempo_color").state == STATE_UNAVAILABLE
    assert state(hass, entry, "tempo_color_today").state == STATE_UNKNOWN
    assert state(hass, entry, "current_period").state == "peak"
    assert state(hass, entry, "red_peak_price").state == "0.7295"


async def test_tomorrow_color_is_asked_from_its_publication_time(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The color of tomorrow is asked from 10:30, then every 15 minutes."""
    freezer.move_to(paris(2026, 11, 11, 10, 0))
    source = FakeTempoSource({YESTERDAY: WHITE, TODAY: RED})
    entry = await setup_contract(hass, TariffOption.TEMPO, tempo=source)
    assert source.requests == [(YESTERDAY, TODAY)]

    await _at(hass, freezer, paris(2026, 11, 11, 10, 29), source)
    assert len(source.requests) == 1

    await _at(hass, freezer, paris(2026, 11, 11, 10, 30), source)
    assert source.requests[-1] == (TOMORROW,)
    assert state(hass, entry, "tempo_color_tomorrow").state == STATE_UNKNOWN

    await _at(hass, freezer, paris(2026, 11, 11, 10, 40), source)
    assert len(source.requests) == 2

    source.colors[TOMORROW] = BLUE
    await _at(hass, freezer, paris(2026, 11, 11, 10, 45), source)
    assert source.requests[-1] == (TOMORROW,)
    assert state(hass, entry, "tempo_color_tomorrow").state == "blue"

    # Once known, nothing is asked until the next publication time.
    await _at(hass, freezer, paris(2026, 11, 11, 23, 0), source)
    await _at(hass, freezer, paris(2026, 11, 12, 7, 0), source)
    assert len(source.requests) == 3
    assert state(hass, entry, "tempo_color").state == "blue"
    assert state(hass, entry, "tempo_color_yesterday").state == "red"


async def test_colors_are_saved_and_reused_after_a_restart(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
) -> None:
    """Known colors are saved, so that a restart does not ask them again."""
    freezer.move_to(paris(2026, 11, 11, 9, 0))
    source = FakeTempoSource({YESTERDAY: WHITE, TODAY: RED})
    entry = await setup_contract(hass, TariffOption.TEMPO, tempo=source)
    assert hass_storage[COLORS_STORAGE]["data"] == {
        "2026-11-10": "white",
        "2026-11-11": "red",
    }

    with (
        patch(TEMPO_FETCH, source),
        patch(COORDINATOR_FETCH, return_value=TEMPO_GRID),
    ):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    assert len(source.requests) == 1
    assert state(hass, entry, "tempo_color").state == "red"


async def test_saved_colors_are_used_when_the_source_fails(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failing source keeps the known colors, with one warning per outage."""
    freezer.move_to(paris(2026, 11, 11, 11, 0))
    hass_storage[COLORS_STORAGE] = {
        "version": 1,
        "minor_version": 1,
        "key": COLORS_STORAGE,
        "data": {
            "2026-11-01": "red",
            "2026-11-10": "white",
            "2026-11-11": "red",
            "2026-11-09": "purple",
            "not a date": "blue",
        },
    }

    async def failing(session: object, days: object) -> dict[date, TempoColor]:
        raise TrveEdfError("offline")

    with caplog.at_level(logging.WARNING):
        entry = await setup_contract(hass, TariffOption.TEMPO, tempo=failing)
    assert caplog.text.count("Cannot get the Tempo colors") == 1
    assert state(hass, entry, "tempo_color").state == "red"
    assert hass_storage[COLORS_STORAGE]["data"]["2026-11-01"] == "red"

    caplog.clear()
    with patch(TEMPO_FETCH, failing), caplog.at_level(logging.WARNING):
        freezer.move_to(paris(2026, 11, 11, 11, 15))
        async_fire_time_changed(hass, paris(2026, 11, 11, 11, 15))
        await hass.async_block_till_done()
    assert "Cannot get the Tempo colors" not in caplog.text

    assert state(hass, entry, "current_price").state == "0.7295"
    assert state(hass, entry, "tempo_color_tomorrow").state == STATE_UNKNOWN

    source = FakeTempoSource({TOMORROW: BLUE})
    await _at(hass, freezer, paris(2026, 11, 11, 11, 45), source)
    assert state(hass, entry, "tempo_color_tomorrow").state == "blue"


async def test_the_colors_coordinator_is_shared_by_tempo_contracts(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Tempo contracts share one colors coordinator, stopped with the last one."""
    freezer.move_to(paris(2026, 11, 11, 9, 0))
    source = FakeTempoSource({YESTERDAY: WHITE, TODAY: RED})
    first = await setup_contract(hass, TariffOption.TEMPO, tempo=source)
    second = await setup_contract(hass, TariffOption.TEMPO, power=9, tempo=source)
    assert len(source.requests) == 1
    assert hass.data[DOMAIN][DATA_TEMPO_COLORS].users == 2

    assert await hass.config_entries.async_unload(first.entry_id)
    await hass.async_block_till_done()
    assert state(hass, second, "tempo_color").state == "red"
    assert hass.data[DOMAIN][DATA_TEMPO_COLORS].users == 1

    assert await hass.config_entries.async_unload(second.entry_id)
    await hass.async_block_till_done()
    assert DATA_TEMPO_COLORS not in hass.data[DOMAIN]


async def test_next_price_change_of_a_tempo_contract(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The price of a Tempo contract changes at 22:00 and at 06:00."""
    freezer.move_to(paris(2026, 11, 11, 23, 0))
    source = FakeTempoSource({YESTERDAY: WHITE, TODAY: RED, TOMORROW: BLUE})
    entry = await setup_contract(hass, TariffOption.TEMPO, tempo=source)

    assert state(hass, entry, "current_price").state == "0.1615"
    assert state(hass, entry, "next_price_change").state == "2026-11-12T05:00:00+00:00"
