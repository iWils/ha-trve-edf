"""Coordinator of a TRVE contract: tariff grid download and period clock."""

from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import TrveEdfError, async_fetch_grid
from .const import (
    CONF_OFF_PEAK_HOURS,
    CONF_OPTION,
    CONF_POWER,
    DOMAIN,
    GRID_MAX_AGE,
    GRID_REFRESH_INTERVAL,
)
from .models import OffPeakRange, TariffGrid, TariffOption, TariffPeriod, TariffRow
from .pricing import (
    PARIS,
    current_period,
    next_midnight,
    next_period_change,
    parse_off_peak_ranges,
    row_in_force,
)

_LOGGER = logging.getLogger(__name__)

type TrveEdfConfigEntry = ConfigEntry[TrveEdfCoordinator]


class TrveEdfCoordinator(DataUpdateCoordinator[TariffGrid]):
    """Download the tariff grid of a contract and follow its tariff periods.

    The grid is downloaded once a day. Between downloads, a clock notifies the
    entities at each change of tariff period and at midnight, so that the current
    price is always computed for the right moment without polling.
    """

    config_entry: TrveEdfConfigEntry

    def __init__(self, hass: HomeAssistant, entry: TrveEdfConfigEntry) -> None:
        """Initialize the coordinator of a contract."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=GRID_REFRESH_INTERVAL,
        )
        self.option = TariffOption(entry.data[CONF_OPTION])
        self.power_kva: int = entry.data[CONF_POWER]
        self.off_peak: tuple[OffPeakRange, ...] = ()
        if self.option is TariffOption.HPHC:
            self.off_peak = parse_off_peak_ranges(entry.options[CONF_OFF_PEAK_HOURS])
        self.grid_downloaded_at: datetime | None = None
        self._unsub_clock: CALLBACK_TYPE | None = None

    async def _async_update_data(self) -> TariffGrid:
        """Download the tariff grid of the contract option."""
        try:
            grid = await async_fetch_grid(
                async_get_clientsession(self.hass), self.option
            )
        except TrveEdfError as err:
            raise UpdateFailed(
                f"Cannot get the {self.option} tariff grid: {err}"
            ) from err
        self.grid_downloaded_at = dt_util.utcnow()
        return grid

    def grid_is_trusted(self, now: datetime) -> bool:
        """Tell whether the last downloaded grid is recent enough to be used."""
        return (
            self.data is not None
            and self.grid_downloaded_at is not None
            and now - self.grid_downloaded_at < GRID_MAX_AGE
        )

    def row(self, now: datetime) -> TariffRow | None:
        """Return the tariff row of the contract in force at a moment."""
        if not self.grid_is_trusted(now):
            return None
        return row_in_force(self.data, now.astimezone(PARIS).date(), self.power_kva)

    def period(self, now: datetime) -> TariffPeriod:
        """Return the tariff period at a moment."""
        return current_period(self.option, now, self.off_peak)

    def next_change(self, now: datetime) -> datetime | None:
        """Return the next change of tariff period after a moment."""
        return next_period_change(self.option, now, self.off_peak)

    @callback
    def async_start_clock(self) -> None:
        """Notify the entities when their values may change.

        That is at each change of tariff period, at midnight (a new row of the
        grid may apply) and when the last downloaded grid becomes too old.
        """
        self._schedule_tick(dt_util.utcnow())

    @callback
    def async_stop_clock(self) -> None:
        """Stop the period clock."""
        if self._unsub_clock is not None:
            self._unsub_clock()
            self._unsub_clock = None

    @callback
    def _schedule_tick(self, now: datetime) -> None:
        moments = [next_midnight(now)]
        if (change := self.next_change(now)) is not None:
            moments.append(change)
        if self.grid_downloaded_at is not None:
            expiry = self.grid_downloaded_at + GRID_MAX_AGE
            if expiry > now:
                moments.append(expiry)
        self._unsub_clock = async_track_point_in_utc_time(
            self.hass, self._async_tick, min(moments)
        )

    @callback
    def _async_tick(self, now: datetime) -> None:
        self._unsub_clock = None
        self.async_update_listeners()
        self._schedule_tick(now)
