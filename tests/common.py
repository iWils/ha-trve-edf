"""Helpers shared by the tests of the Home Assistant layer."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.trve_edf.const import (
    CONF_OFF_PEAK_HOURS,
    CONF_OPTION,
    CONF_POWER,
    DOMAIN,
)
from custom_components.trve_edf.models import (
    PriceKey,
    TariffGrid,
    TariffOption,
    TariffRow,
    TempoColor,
)

PARIS = ZoneInfo("Europe/Paris")

COORDINATOR_FETCH = "custom_components.trve_edf.coordinator.async_fetch_grid"
CONFIG_FLOW_FETCH = "custom_components.trve_edf.config_flow.async_fetch_grid"
TEMPO_FETCH = "custom_components.trve_edf.tempo.async_fetch_tempo_colors"

PREVIOUS_START = date(2026, 2, 1)
PREVIOUS_END = date(2026, 7, 31)
CURRENT_START = date(2026, 8, 1)


def paris(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """Return an aware datetime in French time."""
    return datetime(year, month, day, hour, minute, tzinfo=PARIS)


def _row(
    start: date, end: date | None, power: int, subscription: str, **prices: str
) -> TariffRow:
    return TariffRow(
        start=start,
        end=end,
        power_kva=power,
        subscription=Decimal(subscription),
        prices={PriceKey(key): Decimal(price) for key, price in prices.items()},
    )


BASE_GRID = TariffGrid(
    option=TariffOption.BASE,
    rows=(
        _row(PREVIOUS_START, PREVIOUS_END, 6, "188.2", base="0.194"),
        _row(CURRENT_START, None, 3, "145.76", base="0.2001"),
        _row(CURRENT_START, None, 6, "190.81", base="0.2001"),
        _row(CURRENT_START, None, 9, "239.84", base="0.1985"),
    ),
)

HPHC_GRID = TariffGrid(
    option=TariffOption.HPHC,
    rows=(
        _row(
            PREVIOUS_START, PREVIOUS_END, 6, "188.24", peak="0.2065", off_peak="0.1578"
        ),
        _row(CURRENT_START, None, 6, "190.8131821", peak="0.2142", off_peak="0.1589"),
        _row(CURRENT_START, None, 9, "239.8378787", peak="0.2142", off_peak="0.1589"),
    ),
)

TEMPO_PRICES = {
    "blue_peak": "0.1654",
    "blue_off_peak": "0.1356",
    "white_peak": "0.1921",
    "white_off_peak": "0.1536",
    "red_peak": "0.7295",
    "red_off_peak": "0.1615",
}

TEMPO_GRID = TariffGrid(
    option=TariffOption.TEMPO,
    rows=(
        _row(CURRENT_START, None, 6, "189.9802924", **TEMPO_PRICES),
        _row(CURRENT_START, None, 9, "237.3436191", **TEMPO_PRICES),
    ),
)

GRIDS = {
    TariffOption.BASE: BASE_GRID,
    TariffOption.HPHC: HPHC_GRID,
    TariffOption.TEMPO: TEMPO_GRID,
}


type TempoSource = Callable[[object, Sequence[date]], Awaitable[dict[date, TempoColor]]]
"""Replacement of the function that gets the Tempo colors."""


class FakeTempoSource:
    """Simulated Tempo color source: it knows the colors of ``colors``."""

    def __init__(self, colors: Mapping[date, TempoColor] | None = None) -> None:
        """Initialize the source with its known colors."""
        self.colors: dict[date, TempoColor] = dict(colors or {})
        self.requests: list[tuple[date, ...]] = []

    async def __call__(
        self, session: object, days: Sequence[date]
    ) -> dict[date, TempoColor]:
        """Return the known colors of the requested days."""
        self.requests.append(tuple(days))
        return {day: self.colors[day] for day in days if day in self.colors}


async def setup_contract(
    hass: HomeAssistant,
    option: TariffOption,
    power: int = 6,
    off_peak: str | None = None,
    tempo: TempoSource | None = None,
) -> MockConfigEntry:
    """Add and set up a contract whose downloads are simulated."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"Contract {option} {power} kVA",
        data={CONF_OPTION: option.value, CONF_POWER: power},
        options={} if off_peak is None else {CONF_OFF_PEAK_HOURS: off_peak},
    )
    entry.add_to_hass(hass)
    with (
        patch(COORDINATOR_FETCH, return_value=GRIDS[option]),
        patch(TEMPO_FETCH, tempo or FakeTempoSource()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def entity_id(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> str | None:
    """Return the entity id of a sensor of a contract, if it exists."""
    return er.async_get(hass).async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{entry.entry_id}_{key}"
    )


def state(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> State:
    """Return the state of a sensor of a contract."""
    sensor = entity_id(hass, entry, key)
    assert sensor is not None, f"no {key} sensor"
    current = hass.states.get(sensor)
    assert current is not None
    return current
