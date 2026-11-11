"""Tempo colors, shared by all the Tempo contracts."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import TrveEdfError, async_fetch_tempo_colors
from .const import DOMAIN
from .models import TempoColor
from .pricing import (
    PARIS,
    TEMPO_RETRY_INTERVAL,
    next_tempo_refresh,
    tempo_days_missing,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
COLORS_KEPT = timedelta(days=7)
"""Known colors older than this are forgotten."""

REFRESH_MARGIN = timedelta(seconds=2)
"""Delay added to each scheduled refresh.

Home Assistant may run a scheduled refresh up to about a second early: without
this margin, a refresh planned for 10:30 could run at 10:29:59, find nothing to
ask yet and plan itself again a fraction of a second later, over and over.
"""

DATA_TEMPO_COLORS = "tempo_colors"
"""Key of the shared coordinator in ``hass.data[DOMAIN]``."""


class TempoColorsCoordinator(DataUpdateCoordinator[dict[date, TempoColor]]):
    """Get the Tempo colors needed by the Tempo contracts.

    Only the missing colors of yesterday, today and, once published, tomorrow are
    asked for. Known colors are saved and never asked again. The next request is
    scheduled by the publication rules: shortly after a failure or while an
    expected color is missing, otherwise when the next color may be published.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the coordinator of the Tempo colors."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=None,
            name=f"{DOMAIN} Tempo colors",
            update_interval=TEMPO_RETRY_INTERVAL,
        )
        self._store: Store[dict[str, str]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.tempo_colors"
        )
        self.users = 0
        self.started = asyncio.Event()
        self._failing = False

    async def async_start(self) -> None:
        """Publish the saved colors at once, then get the missing ones.

        The missing colors are asked for in the background, so that the setup of
        the contracts never waits for the network.
        """
        try:
            self.async_set_updated_data(await self._async_load(dt_util.utcnow()))
        finally:
            self.started.set()
        self.hass.async_create_background_task(
            self.async_refresh(), f"{DOMAIN} Tempo colors first refresh"
        )

    async def _async_update_data(self) -> dict[date, TempoColor]:
        """Get the missing Tempo colors, keeping the known ones."""
        now = dt_util.utcnow()
        colors = dict(self.data or {})
        if missing := tempo_days_missing(now, colors):
            try:
                fetched = await async_fetch_tempo_colors(
                    async_get_clientsession(self.hass), missing
                )
            except TrveEdfError as err:
                if not self._failing:
                    _LOGGER.warning(
                        "Cannot get the Tempo colors (%s): trying again later", err
                    )
                self._failing = True
            else:
                if self._failing:
                    _LOGGER.info("The Tempo colors can be retrieved again")
                self._failing = False
                if fetched:
                    colors = _recent({**colors, **fetched}, now)
                    await self._store.async_save(
                        {day.isoformat(): color.value for day, color in colors.items()}
                    )
        self.update_interval = next_tempo_refresh(now, colors) - now + REFRESH_MARGIN
        return colors

    async def _async_load(self, now: datetime) -> dict[date, TempoColor]:
        """Return the saved colors that are still useful."""
        try:
            saved: Any = await self._store.async_load()
        except Exception as err:
            _LOGGER.warning("Cannot read the saved Tempo colors: %s", err)
            saved = None
        colors: dict[date, TempoColor] = {}
        if isinstance(saved, dict):
            for day, color in saved.items():
                try:
                    colors[date.fromisoformat(day)] = TempoColor(color)
                except (TypeError, ValueError):
                    continue
        return _recent(colors, now)


def _recent(colors: Mapping[date, TempoColor], now: datetime) -> dict[date, TempoColor]:
    oldest = now.astimezone(PARIS).date() - COLORS_KEPT
    return {day: color for day, color in colors.items() if day >= oldest}


async def async_acquire_tempo_colors(hass: HomeAssistant) -> TempoColorsCoordinator:
    """Return the shared coordinator of the Tempo colors, starting it if needed.

    It returns once the saved colors are published, without waiting for the
    network. Each call must be balanced by ``async_release_tempo_colors``.
    """
    domain_data: dict[str, Any] = hass.data.setdefault(DOMAIN, {})
    coordinator: TempoColorsCoordinator | None = domain_data.get(DATA_TEMPO_COLORS)
    if coordinator is None:
        coordinator = TempoColorsCoordinator(hass)
        domain_data[DATA_TEMPO_COLORS] = coordinator
        try:
            await coordinator.async_start()
        except BaseException:
            if domain_data.get(DATA_TEMPO_COLORS) is coordinator:
                del domain_data[DATA_TEMPO_COLORS]
            raise
    else:
        await coordinator.started.wait()
    coordinator.users += 1
    return coordinator


async def async_release_tempo_colors(
    hass: HomeAssistant, coordinator: TempoColorsCoordinator
) -> None:
    """Stop the shared coordinator of the Tempo colors once no contract uses it."""
    coordinator.users -= 1
    if coordinator.users > 0:
        return
    domain_data: dict[str, Any] = hass.data.get(DOMAIN, {})
    if domain_data.get(DATA_TEMPO_COLORS) is coordinator:
        del domain_data[DATA_TEMPO_COLORS]
    await coordinator.async_shutdown()
