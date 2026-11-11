"""Data models shared by the tariff rules, the data clients and the entities.

This module holds data only: the rules that use it live in ``pricing.py``. It has
no Home Assistant dependency.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final


class TariffOption(StrEnum):
    """Regulated tariff option (TRVE) of a contract."""

    BASE = "base"
    HPHC = "hphc"


class TariffPeriod(StrEnum):
    """Tariff period: each one has its own price of the kWh."""

    BASE = "base"
    PEAK = "peak"
    OFF_PEAK = "off_peak"


OPTION_PERIODS: Final[Mapping[TariffOption, tuple[TariffPeriod, ...]]] = {
    TariffOption.BASE: (TariffPeriod.BASE,),
    TariffOption.HPHC: (TariffPeriod.PEAK, TariffPeriod.OFF_PEAK),
}
"""Periods priced by each option."""


@dataclass(frozen=True, slots=True)
class TariffRow:
    """Prices of one subscribed power during one validity period.

    Attributes:
        start: First day of validity.
        end: Last day of validity (included), or None while the row is in force.
        power_kva: Subscribed power, in kVA.
        subscription: Yearly subscription, in euros, taxes included.
        prices: Price of the kWh of each period of the option, in euros, taxes
            included.
    """

    start: date
    end: date | None
    power_kva: int
    subscription: Decimal
    prices: Mapping[TariffPeriod, Decimal]


@dataclass(frozen=True, slots=True)
class TariffGrid:
    """Regulated tariff grid of one option, with all its validity periods."""

    option: TariffOption
    rows: tuple[TariffRow, ...]


def grid_to_dict(grid: TariffGrid) -> dict[str, Any]:
    """Convert a tariff grid to JSON-compatible data (amounts kept exact)."""
    return {
        "option": grid.option.value,
        "rows": [
            {
                "start": row.start.isoformat(),
                "end": None if row.end is None else row.end.isoformat(),
                "power_kva": row.power_kva,
                "subscription": str(row.subscription),
                "prices": {
                    period.value: str(price) for period, price in row.prices.items()
                },
            }
            for row in grid.rows
        ],
    }


def grid_from_dict(data: Any) -> TariffGrid | None:
    """Rebuild a tariff grid from data made by ``grid_to_dict``.

    Returns:
        The grid, or None if the data is not a valid grid.
    """
    try:
        option = TariffOption(data["option"])
        rows = tuple(
            TariffRow(
                start=date.fromisoformat(row["start"]),
                end=None if row["end"] is None else date.fromisoformat(row["end"]),
                power_kva=int(row["power_kva"]),
                subscription=Decimal(row["subscription"]),
                prices={
                    TariffPeriod(period): Decimal(price)
                    for period, price in row["prices"].items()
                },
            )
            for row in data["rows"]
        )
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError):
        return None
    if not rows or any(set(row.prices) != set(OPTION_PERIODS[option]) for row in rows):
        return None
    return TariffGrid(option=option, rows=rows)


@dataclass(frozen=True, slots=True)
class OffPeakRange:
    """Daily off-peak range: from start (included) to end (excluded).

    The range crosses midnight when end is before start, for example 22:00-06:00.
    """

    start: time
    end: time
