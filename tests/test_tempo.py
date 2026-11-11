"""Tests of the Tempo option: colors, prices and the shared colors coordinator."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
import logging
from typing import Any
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    EVENT_STATE_CHANGED,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.trve_edf.api import TrveEdfError
from custom_components.trve_edf.const import CONF_OPTION, CONF_POWER, DOMAIN
from custom_components.trve_edf.models import TariffOption, TempoColor
from custom_components.trve_edf.tempo import (
    DATA_TEMPO_COLORS,
    TempoColorsCoordinator,
    async_acquire_tempo_colors,
    async_release_tempo_colors,
)

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
        await hass.async_block_till_done(wait_background_tasks=True)


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
    assert state(hass, entry, "tempo_color_today").state == STATE_UNAVAILABLE
    assert state(hass, entry, "tempo_color_yesterday").state == STATE_UNAVAILABLE
    assert state(hass, entry, "tempo_color_tomorrow").state == STATE_UNKNOWN
    assert state(hass, entry, "current_period").state == "peak"
    assert state(hass, entry, "red_peak_price").state == "0.7295"


async def test_tomorrow_color_is_asked_from_its_publication_time(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The color of tomorrow is asked from 10:30, then every 15 minutes.

    Each scheduled refresh runs 2 seconds after its planned moment (margin).
    """
    freezer.move_to(paris(2026, 11, 11, 10, 0))
    source = FakeTempoSource({YESTERDAY: WHITE, TODAY: RED})
    entry = await setup_contract(hass, TariffOption.TEMPO, tempo=source)
    assert source.requests == [(YESTERDAY, TODAY)]

    await _at(hass, freezer, paris(2026, 11, 11, 10, 29), source)
    assert len(source.requests) == 1

    await _at(hass, freezer, paris(2026, 11, 11, 10, 31), source)
    assert source.requests[-1] == (TOMORROW,)
    assert state(hass, entry, "tempo_color_tomorrow").state == STATE_UNKNOWN

    await _at(hass, freezer, paris(2026, 11, 11, 10, 45), source)
    assert len(source.requests) == 2

    source.colors[TOMORROW] = BLUE
    await _at(hass, freezer, paris(2026, 11, 11, 10, 47), source)
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
        await hass.async_block_till_done(wait_background_tasks=True)

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
        freezer.move_to(paris(2026, 11, 11, 11, 16))
        async_fire_time_changed(hass, paris(2026, 11, 11, 11, 16))
        await hass.async_block_till_done(wait_background_tasks=True)
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
    await hass.async_block_till_done(wait_background_tasks=True)
    assert state(hass, second, "tempo_color").state == "red"
    assert hass.data[DOMAIN][DATA_TEMPO_COLORS].users == 1

    assert await hass.config_entries.async_unload(second.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
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


def saved_colors(colors: dict[str, str]) -> dict[str, Any]:
    """Return the storage content of saved Tempo colors."""
    return {"version": 1, "minor_version": 1, "key": COLORS_STORAGE, "data": colors}


def tempo_entry(hass: HomeAssistant, power: int = 6) -> MockConfigEntry:
    """Add a Tempo contract without setting it up."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"Tempo {power} kVA",
        data={CONF_OPTION: "tempo", CONF_POWER: power},
    )
    entry.add_to_hass(hass)
    return entry


async def test_a_refresh_run_just_before_10_30_does_not_loop(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A refresh run slightly early plans the next one with a margin."""
    freezer.move_to(paris(2026, 11, 11, 10, 0))
    source = FakeTempoSource({YESTERDAY: WHITE, TODAY: RED})
    await setup_contract(hass, TariffOption.TEMPO, tempo=source)
    coordinator: TempoColorsCoordinator = hass.data[DOMAIN][DATA_TEMPO_COLORS]

    freezer.move_to(paris(2026, 11, 11, 10, 29) + timedelta(seconds=59.5))
    with patch(TEMPO_FETCH, source):
        await coordinator.async_refresh()

    assert coordinator.update_interval is not None
    assert coordinator.update_interval >= timedelta(seconds=1)


async def test_contracts_set_up_together_show_the_saved_colors_at_once(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
) -> None:
    """Two Tempo contracts set up together never show unavailable colors."""
    freezer.move_to(paris(2026, 11, 11, 9, 0))
    hass_storage[COLORS_STORAGE] = saved_colors(
        {"2026-11-10": "white", "2026-11-11": "red"}
    )
    first, second = tempo_entry(hass), tempo_entry(hass, power=9)
    seen: list[tuple[str, str]] = []

    def record(event: Event[EventStateChangedData]) -> None:
        if (new_state := event.data["new_state"]) is not None:
            seen.append((event.data["entity_id"], new_state.state))

    hass.bus.async_listen(EVENT_STATE_CHANGED, record)
    with (
        patch(COORDINATOR_FETCH, return_value=TEMPO_GRID),
        patch(TEMPO_FETCH, FakeTempoSource()),
    ):
        await asyncio.gather(
            hass.config_entries.async_setup(first.entry_id),
            hass.config_entries.async_setup(second.entry_id),
        )
        await hass.async_block_till_done(wait_background_tasks=True)

    colors = {entity_id(hass, entry, "tempo_color") for entry in (first, second)}
    assert {state for sensor, state in seen if sensor in colors} == {"red"}


async def test_the_setup_does_not_wait_for_the_colors_source(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
) -> None:
    """The saved colors are shown while the missing ones are being asked."""
    freezer.move_to(paris(2026, 11, 11, 11, 0))
    hass_storage[COLORS_STORAGE] = saved_colors(
        {"2026-11-10": "white", "2026-11-11": "red"}
    )
    answer = asyncio.Event()
    requests: list[tuple[date, ...]] = []

    async def slow(session: object, days: tuple[date, ...]) -> dict[date, TempoColor]:
        requests.append(tuple(days))
        await answer.wait()
        return {TOMORROW: BLUE}

    entry = tempo_entry(hass)
    with patch(COORDINATOR_FETCH, return_value=TEMPO_GRID), patch(TEMPO_FETCH, slow):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        assert state(hass, entry, "tempo_color").state == "red"
        assert requests == [(TOMORROW,)]

        answer.set()
        await hass.async_block_till_done(wait_background_tasks=True)
    assert state(hass, entry, "tempo_color_tomorrow").state == "blue"


async def test_old_colors_are_dropped_when_saving(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
) -> None:
    """Colors older than 7 days are not saved again."""
    freezer.move_to(paris(2026, 11, 11, 11, 0))
    hass_storage[COLORS_STORAGE] = saved_colors(
        {"2026-11-01": "red", "2026-11-10": "white", "2026-11-11": "red"}
    )
    await setup_contract(
        hass, TariffOption.TEMPO, tempo=FakeTempoSource({TOMORROW: BLUE})
    )

    assert hass_storage[COLORS_STORAGE]["data"] == {
        "2026-11-10": "white",
        "2026-11-11": "red",
        "2026-11-12": "blue",
    }


async def test_a_failed_grid_releases_the_colors(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A Tempo contract whose setup fails does not keep the colors running."""
    freezer.move_to(paris(2026, 11, 11, 9, 0))
    entry = tempo_entry(hass)
    with (
        patch(COORDINATOR_FETCH, side_effect=TrveEdfError("offline")),
        patch(TEMPO_FETCH, FakeTempoSource()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert DATA_TEMPO_COLORS not in hass.data[DOMAIN]


async def test_unreadable_saved_colors_are_ignored(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A storage error is logged and the colors are asked again."""
    freezer.move_to(paris(2026, 11, 11, 9, 0))

    class BrokenStore:
        def __init__(self, *args: object) -> None:
            pass

        async def async_load(self) -> None:
            raise NotImplementedError("saved by a newer version")

        async def async_save(self, data: object) -> None:
            pass

    source = FakeTempoSource({YESTERDAY: WHITE, TODAY: RED})
    with patch("custom_components.trve_edf.tempo.Store", BrokenStore):
        entry = await setup_contract(hass, TariffOption.TEMPO, tempo=source)

    assert source.requests == [(YESTERDAY, TODAY)]
    assert state(hass, entry, "tempo_color").state == "red"


async def test_a_failed_start_does_not_leave_the_colors_coordinator(
    hass: HomeAssistant,
) -> None:
    """If starting the shared coordinator fails, it is not kept for later setups."""
    with (
        patch.object(
            TempoColorsCoordinator, "async_start", side_effect=RuntimeError("boom")
        ),
        pytest.raises(RuntimeError),
    ):
        await async_acquire_tempo_colors(hass)

    assert DATA_TEMPO_COLORS not in hass.data[DOMAIN]


async def test_releasing_a_coordinator_that_is_no_longer_shared(
    hass: HomeAssistant,
) -> None:
    """A released coordinator is shut down even if another one replaced it."""
    replaced = TempoColorsCoordinator(hass)
    replaced.users = 1
    current = TempoColorsCoordinator(hass)
    hass.data.setdefault(DOMAIN, {})[DATA_TEMPO_COLORS] = current

    await async_release_tempo_colors(hass, replaced)

    assert replaced.users == 0
    assert hass.data[DOMAIN][DATA_TEMPO_COLORS] is current
