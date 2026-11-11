"""Coordinator of a TRVE contract: tariff grid download and period clock."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
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
from .models import (
    OffPeakRange,
    PriceKey,
    TariffGrid,
    TariffOption,
    TariffPeriod,
    TariffRow,
    TempoColor,
    grid_from_dict,
    grid_to_dict,
)
from .pricing import (
    PARIS,
    current_period,
    current_price,
    next_midnight,
    next_period_change,
    parse_off_peak_ranges,
    price_key,
    row_in_force,
    tempo_color,
)

if TYPE_CHECKING:
    from .tempo import TempoColorsCoordinator

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1

type TrveEdfConfigEntry = ConfigEntry[TrveEdfCoordinator]


class TrveEdfCoordinator(DataUpdateCoordinator[TariffGrid]):
    """Get the tariff grid of a contract and follow its tariff periods.

    The grid is downloaded once a day and saved, shared by the contracts of the
    same option: a grid saved less than a day ago is reused without download, and
    after a restart while the CRE cannot be reached, a saved grid younger than
    7 days is used. Between downloads, a clock notifies the entities whenever
    their values may change, so that they are always computed for the right
    moment without polling.
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
        self.tempo: TempoColorsCoordinator | None = None
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.grid_{self.option}"
        )
        self._unsub_clock: CALLBACK_TYPE | None = None

    async def _async_update_data(self) -> TariffGrid:
        """Get the tariff grid of the contract option."""
        now = dt_util.utcnow()
        saved = await self._async_load_saved_grid()
        if saved is not None and now - saved[1] < GRID_REFRESH_INTERVAL:
            self.grid_downloaded_at = saved[1]
            return saved[0]

        try:
            grid = await async_fetch_grid(
                async_get_clientsession(self.hass),
                self.option,
                today=now.astimezone(PARIS).date(),
            )
        except TrveEdfError as err:
            if (
                self.data is None
                and saved is not None
                and now - saved[1] < GRID_MAX_AGE
            ):
                _LOGGER.warning(
                    "Cannot download the %s tariff grid (%s): using the grid saved"
                    " on %s",
                    self.option,
                    err,
                    saved[1].isoformat(),
                )
                self.grid_downloaded_at = saved[1]
                return saved[0]
            raise UpdateFailed(
                f"Cannot get the {self.option} tariff grid: {err}"
            ) from err

        self.grid_downloaded_at = now
        await self._store.async_save(
            {"downloaded_at": now.isoformat(), "grid": grid_to_dict(grid)}
        )
        return grid

    async def _async_load_saved_grid(self) -> tuple[TariffGrid, datetime] | None:
        """Return the saved grid of the option and its download time, if valid."""
        data = await self._store.async_load()
        if not isinstance(data, dict):
            return None
        grid = grid_from_dict(data.get("grid"))
        downloaded_at = dt_util.parse_datetime(str(data.get("downloaded_at")))
        if grid is None or grid.option is not self.option or downloaded_at is None:
            return None
        return grid, downloaded_at

    @property
    def power_issue_id(self) -> str:
        """Return the id of the repair issue of a power missing from the grid."""
        return f"power_not_available_{self.config_entry.entry_id}"

    @callback
    def async_update_listeners(self) -> None:
        """Check that the power is still in the grid, then notify the entities."""
        self._async_check_power(dt_util.utcnow())
        super().async_update_listeners()

    @callback
    def _async_check_power(self, now: datetime) -> None:
        """Raise or clear the repair issue of a power missing from the grid.

        Nothing is decided while the grid is not trusted.
        """
        if not self.grid_is_trusted(now):
            return
        if row_in_force(self.data, now.astimezone(PARIS).date(), self.power_kva):
            ir.async_delete_issue(self.hass, DOMAIN, self.power_issue_id)
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self.power_issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="power_not_available",
            translation_placeholders={
                "title": self.config_entry.title,
                "power": str(self.power_kva),
            },
        )

    def grid_is_trusted(self, now: datetime) -> bool:
        """Tell whether the grid in use is recent enough to be trusted."""
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

    def price_key(self, now: datetime) -> PriceKey | None:
        """Return the key of the price of the kWh in force at a moment.

        For Tempo, it depends on the color of the Tempo day: None while unknown.
        """
        color = self.tempo_color(now) if self.option is TariffOption.TEMPO else None
        return price_key(self.option, self.period(now), color)

    @callback
    def async_attach_tempo(self, tempo: TempoColorsCoordinator) -> None:
        """Follow the shared Tempo colors: notify the entities when they change."""
        self.tempo = tempo
        self.config_entry.async_on_unload(
            tempo.async_add_listener(self.async_update_listeners)
        )

    def tempo_colors(self) -> Mapping[date, TempoColor]:
        """Return the known Tempo colors."""
        if self.tempo is None or self.tempo.data is None:
            return {}
        return self.tempo.data

    def tempo_color(self, now: datetime) -> TempoColor | None:
        """Return the color of the Tempo day in force at a moment (06:00-06:00)."""
        return tempo_color(self.tempo_colors(), now)

    def tempo_color_of_day(self, day: date) -> TempoColor | None:
        """Return the color of the Tempo day starting at 06:00 on a date."""
        return self.tempo_colors().get(day)

    def next_change(self, now: datetime) -> datetime | None:
        """Return the next change of tariff period after a moment."""
        return next_period_change(self.option, now, self.off_peak)

    def next_price_change(self, now: datetime) -> datetime | None:
        """Return the next moment the price of the kWh changes.

        The price changes with the tariff period, and at midnight when a new row of
        the grid applies with another price.
        """
        change = self.next_change(now)
        midnight = next_midnight(now)
        if change is not None and change <= midnight:
            return change
        if self.grid_is_trusted(now) and self._price(now) != self._price(midnight):
            return midnight
        return change

    def _price(self, moment: datetime) -> Decimal | None:
        row = row_in_force(self.data, moment.astimezone(PARIS).date(), self.power_kva)
        if row is None or (key := self.price_key(moment)) is None:
            return None
        return current_price(row, key)

    @callback
    def async_start_clock(self) -> None:
        """Notify the entities when their values may change.

        That is at each change of tariff period, at midnight (a new row of the
        grid may apply) and when the grid in use becomes too old.
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
        # Schedule the next tick first, so that an error in a listener cannot stop
        # the clock.
        self._schedule_tick(now)
        self.async_update_listeners()
