"""Diagnostics of the EDF regulated tariffs (TRVE) integration.

They tell what the prices of a contract are computed from at the moment they are
downloaded: the contract, the tariff grid in use and its age, the period and
price in force and, for Tempo, the known colors. The integration uses no
credential and no personal data, and nothing from the network session is
included.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.diagnostics import REDACTED
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .coordinator import TrveEdfConfigEntry, TrveEdfCoordinator
from .models import TariffOption, TariffRow
from .pricing import PARIS, available_powers, current_price, format_off_peak_ranges


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TrveEdfConfigEntry
) -> dict[str, Any]:
    """Return the diagnostics of a contract, as JSON-compatible data.

    Amounts are exact decimal strings. Instants are ISO 8601 texts with their
    offset; the next price change is given in Paris time, like the rules. The
    title, which the user may have chosen, is redacted. A contract that is not
    loaded only has its entry part.
    """
    entry_data = {
        "title": REDACTED,
        "version": entry.version,
        "state": entry.state.value,
        "data": dict(entry.data),
        "options": dict(entry.options),
    }
    if entry.state is not ConfigEntryState.LOADED:
        return {"entry": entry_data}
    coordinator = entry.runtime_data
    now = dt_util.utcnow()
    return {
        "entry": entry_data,
        "contract": {
            "option": coordinator.option.value,
            "power_kva": coordinator.power_kva,
            "off_peak_hours": format_off_peak_ranges(coordinator.off_peak),
        },
        "grid": _grid(coordinator, now),
        "now": _now(coordinator, now),
        "tempo": _tempo(coordinator),
    }


def _grid(coordinator: TrveEdfCoordinator, now: datetime) -> dict[str, Any]:
    """Describe the tariff grid in use and the row of the contract in force."""
    today = now.astimezone(PARIS).date()
    downloaded_at = coordinator.grid_downloaded_at
    return {
        "downloaded_at": None if downloaded_at is None else downloaded_at.isoformat(),
        "trusted": coordinator.grid_is_trusted(now),
        "last_update_success": coordinator.last_update_success,
        "rows": len(coordinator.data.rows),
        "today": today.isoformat(),
        "powers_in_force_today": list(available_powers(coordinator.data, today)),
        "row_in_force": _row(coordinator.row(now)),
    }


def _row(row: TariffRow | None) -> dict[str, Any] | None:
    """Describe a tariff row, amounts kept exact."""
    if row is None:
        return None
    return {
        "start": row.start.isoformat(),
        "end": None if row.end is None else row.end.isoformat(),
        "power_kva": row.power_kva,
        "subscription": str(row.subscription),
        "prices": {key.value: str(price) for key, price in row.prices.items()},
    }


def _now(coordinator: TrveEdfCoordinator, now: datetime) -> dict[str, Any]:
    """Describe the period and the price in force, as the sensors compute them."""
    row = coordinator.row(now)
    key = coordinator.price_key(now)
    price = None if row is None or key is None else current_price(row, key)
    change = coordinator.next_price_change(now)
    return {
        "utc": now.isoformat(),
        "paris": now.astimezone(PARIS).isoformat(),
        "period": coordinator.period(now).value,
        "price_key": None if key is None else key.value,
        "price": None if price is None else str(price),
        "next_price_change": (
            None if change is None else change.astimezone(PARIS).isoformat()
        ),
    }


def _tempo(coordinator: TrveEdfCoordinator) -> dict[str, Any] | None:
    """Describe the known Tempo colors and their refresh, for a Tempo contract."""
    tempo = coordinator.tempo
    if coordinator.option is not TariffOption.TEMPO or tempo is None:
        return None
    interval = tempo.update_interval
    return {
        "colors": {
            day.isoformat(): color.value
            for day, color in sorted(coordinator.tempo_colors().items())
        },
        "last_update_success": tempo.last_update_success,
        "update_interval_seconds": (
            None if interval is None else interval.total_seconds()
        ),
    }
