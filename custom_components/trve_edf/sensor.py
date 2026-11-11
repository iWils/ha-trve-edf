"""Sensors of the EDF regulated tariffs (TRVE) integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import TrveEdfConfigEntry, TrveEdfCoordinator
from .entity import TrveEdfEntity
from .models import OPTION_PERIODS, PriceKey, TariffOption, TempoColor
from .pricing import PARIS, current_price

PARALLEL_UPDATES = 0

PRICE_UNIT = "EUR/kWh"

type SensorValue = Decimal | str | datetime | None


@dataclass(frozen=True, kw_only=True)
class TrveEdfSensorDescription(SensorEntityDescription):
    """Description of a TRVE sensor."""

    options_supported: frozenset[TariffOption]
    """Tariff options that have this sensor."""

    value_fn: Callable[[TrveEdfCoordinator, datetime], SensorValue]
    """Value of the sensor at a moment; None when it is not known."""

    unknown_is_a_state: bool = False
    """When the value is not known: unknown state if True, else unavailable."""


def _current_price(coordinator: TrveEdfCoordinator, now: datetime) -> SensorValue:
    if (row := coordinator.row(now)) is None:
        return None
    if (key := coordinator.price_key(now)) is None:
        return None
    return current_price(row, key)


def _price(key: PriceKey) -> Callable[[TrveEdfCoordinator, datetime], SensorValue]:
    def value(coordinator: TrveEdfCoordinator, now: datetime) -> SensorValue:
        if (row := coordinator.row(now)) is None:
            return None
        return current_price(row, key)

    return value


def _tempo_color(
    coordinator: TrveEdfCoordinator, now: datetime
) -> SensorValue:
    color = coordinator.tempo_color(now)
    return None if color is None else color.value


def _tempo_color_of_day(
    days_from_today: int,
) -> Callable[[TrveEdfCoordinator, datetime], SensorValue]:
    def value(coordinator: TrveEdfCoordinator, now: datetime) -> SensorValue:
        day = now.astimezone(PARIS).date() + timedelta(days=days_from_today)
        color = coordinator.tempo_color_of_day(day)
        return None if color is None else color.value

    return value


def _subscription(coordinator: TrveEdfCoordinator, now: datetime) -> SensorValue:
    if (row := coordinator.row(now)) is None:
        return None
    return row.subscription


def _price_description(
    key: str,
    value_fn: Callable[[TrveEdfCoordinator, datetime], SensorValue],
    options: frozenset[TariffOption],
) -> TrveEdfSensorDescription:
    return TrveEdfSensorDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=PRICE_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        options_supported=options,
        value_fn=value_fn,
    )


ALL_OPTIONS = frozenset(TariffOption)
TEMPO = frozenset({TariffOption.TEMPO})
TEMPO_COLORS = [color.value for color in TempoColor]


def _color_description(
    key: str,
    value_fn: Callable[[TrveEdfCoordinator, datetime], SensorValue],
    *,
    unknown_is_a_state: bool,
) -> TrveEdfSensorDescription:
    return TrveEdfSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.ENUM,
        options=TEMPO_COLORS,
        options_supported=TEMPO,
        value_fn=value_fn,
        unknown_is_a_state=unknown_is_a_state,
    )


SENSORS: tuple[TrveEdfSensorDescription, ...] = (
    _price_description("current_price", _current_price, ALL_OPTIONS),
    TrveEdfSensorDescription(
        key="current_period",
        translation_key="current_period",
        device_class=SensorDeviceClass.ENUM,
        options_supported=ALL_OPTIONS,
        value_fn=lambda coordinator, now: coordinator.period(now).value,
    ),
    TrveEdfSensorDescription(
        key="next_price_change",
        translation_key="next_price_change",
        device_class=SensorDeviceClass.TIMESTAMP,
        options_supported=frozenset({TariffOption.HPHC, TariffOption.TEMPO}),
        value_fn=lambda coordinator, now: coordinator.next_price_change(now),
    ),
    TrveEdfSensorDescription(
        key="subscription",
        translation_key="subscription",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="EUR",
        suggested_display_precision=2,
        options_supported=ALL_OPTIONS,
        value_fn=_subscription,
    ),
    _price_description(
        "base_price",
        _price(PriceKey.BASE),
        frozenset({TariffOption.BASE}),
    ),
    _price_description(
        "peak_price",
        _price(PriceKey.PEAK),
        frozenset({TariffOption.HPHC}),
    ),
    _price_description(
        "off_peak_price",
        _price(PriceKey.OFF_PEAK),
        frozenset({TariffOption.HPHC}),
    ),
    *(
        _price_description(f"{key.value}_price", _price(key), TEMPO)
        for key in (
            PriceKey.BLUE_PEAK,
            PriceKey.BLUE_OFF_PEAK,
            PriceKey.WHITE_PEAK,
            PriceKey.WHITE_OFF_PEAK,
            PriceKey.RED_PEAK,
            PriceKey.RED_OFF_PEAK,
        )
    ),
    _color_description("tempo_color", _tempo_color, unknown_is_a_state=False),
    _color_description(
        "tempo_color_yesterday", _tempo_color_of_day(-1), unknown_is_a_state=True
    ),
    _color_description(
        "tempo_color_today", _tempo_color_of_day(0), unknown_is_a_state=True
    ),
    _color_description(
        "tempo_color_tomorrow", _tempo_color_of_day(1), unknown_is_a_state=True
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TrveEdfConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the sensors of a contract."""
    coordinator = entry.runtime_data
    async_add_entities(
        TrveEdfSensor(coordinator, description)
        for description in SENSORS
        if coordinator.option in description.options_supported
    )


class TrveEdfSensor(TrveEdfEntity, SensorEntity):
    """Sensor of a TRVE contract, computed for the current moment."""

    entity_description: TrveEdfSensorDescription

    def __init__(
        self, coordinator: TrveEdfCoordinator, description: TrveEdfSensorDescription
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        if description.device_class is SensorDeviceClass.ENUM and not description.options:
            self._attr_options = [
                period.value for period in OPTION_PERIODS[coordinator.option]
            ]

    @property
    def native_value(self) -> SensorValue:
        """Return the value of the sensor now."""
        return self.entity_description.value_fn(self.coordinator, dt_util.utcnow())

    @property
    def available(self) -> bool:
        """Return whether the sensor has a state now.

        A value that cannot be known for sure makes the sensor unavailable, except
        for the sensors whose unknown value is a normal state (Tempo colors of a
        calendar day, not published yet).
        """
        return self.entity_description.unknown_is_a_state or (
            self.native_value is not None
        )
