"""Sensors of the EDF regulated tariffs (TRVE) integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
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
from .models import OPTION_PERIODS, TariffOption, TariffPeriod
from .pricing import current_price

PARALLEL_UPDATES = 0

PRICE_UNIT = "EUR/kWh"

type SensorValue = Decimal | str | datetime | None


@dataclass(frozen=True, kw_only=True)
class TrveEdfSensorDescription(SensorEntityDescription):
    """Description of a TRVE sensor."""

    options_supported: frozenset[TariffOption]
    """Tariff options that have this sensor."""

    value_fn: Callable[[TrveEdfCoordinator, datetime], SensorValue]
    """Value of the sensor at a moment; None when it cannot be known for sure."""


def _current_price(coordinator: TrveEdfCoordinator, now: datetime) -> SensorValue:
    if (row := coordinator.row(now)) is None:
        return None
    return current_price(row, coordinator.period(now))


def _period_price(
    period: TariffPeriod,
) -> Callable[[TrveEdfCoordinator, datetime], SensorValue]:
    def value(coordinator: TrveEdfCoordinator, now: datetime) -> SensorValue:
        if (row := coordinator.row(now)) is None:
            return None
        return current_price(row, period)

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
        options_supported=frozenset({TariffOption.HPHC}),
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
        _period_price(TariffPeriod.BASE),
        frozenset({TariffOption.BASE}),
    ),
    _price_description(
        "peak_price",
        _period_price(TariffPeriod.PEAK),
        frozenset({TariffOption.HPHC}),
    ),
    _price_description(
        "off_peak_price",
        _period_price(TariffPeriod.OFF_PEAK),
        frozenset({TariffOption.HPHC}),
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
        if description.device_class is SensorDeviceClass.ENUM:
            self._attr_options = [
                period.value for period in OPTION_PERIODS[coordinator.option]
            ]

    @property
    def native_value(self) -> SensorValue:
        """Return the value of the sensor now."""
        return self.entity_description.value_fn(self.coordinator, dt_util.utcnow())

    @property
    def available(self) -> bool:
        """Return whether the value can be known for sure now."""
        return self.native_value is not None
