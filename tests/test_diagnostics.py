"""Tests of the diagnostics."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from http import HTTPStatus
import json
from typing import Any
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.auth.models import Credentials

# Home Assistant 2025.1: the download imports the Supervisor client, whose models
# cannot be built while time is frozen. Import it before any test freezes time.
import homeassistant.components.hassio  # noqa: F401
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import (
    CLIENT_ID,
    MockConfigEntry,
    MockUser,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.trve_edf.api import CreConnectionError
from custom_components.trve_edf.const import DOMAIN
from custom_components.trve_edf.diagnostics import async_get_config_entry_diagnostics
from custom_components.trve_edf.models import TariffOption, TempoColor

from .common import COORDINATOR_FETCH, FakeTempoSource, paris, setup_contract

COLORS_STORAGE = f"{DOMAIN}.tempo_colors"
YESTERDAY = paris(2026, 11, 10).date()
TODAY = paris(2026, 11, 11).date()


type Diagnostics = Callable[[MockConfigEntry], Awaitable[dict[str, Any]]]
"""Download of the diagnostics of a contract."""


@pytest.fixture
def get_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    hass_admin_user: MockUser,
    hass_admin_credential: Credentials,
) -> Diagnostics:
    """Return how to download the diagnostics of a contract, as from the interface.

    The access token is created at the moment of each download: the tests move
    the clock, and a token created at another moment is refused. The encoder of
    the download accepts any object: the data must also be plain JSON, the same
    once through ``json.dumps``.
    """

    async def download(entry: MockConfigEntry) -> dict[str, Any]:
        assert await async_setup_component(hass, "diagnostics", {})
        refresh_token = await hass.auth.async_create_refresh_token(
            hass_admin_user, CLIENT_ID, credential=hass_admin_credential
        )
        client = await hass_client(hass.auth.async_create_access_token(refresh_token))
        response = await client.get(f"/api/diagnostics/config_entry/{entry.entry_id}")
        assert response.status == HTTPStatus.OK
        downloaded: dict[str, Any] = (await response.json())["data"]
        direct = await async_get_config_entry_diagnostics(hass, entry)
        assert json.loads(json.dumps(direct)) == downloaded
        return downloaded

    return download


async def _at(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, when: datetime
) -> None:
    """Move the clock to a moment and let scheduled callbacks run."""
    freezer.move_to(when)
    async_fire_time_changed(hass, when)
    await hass.async_block_till_done()


async def test_base_contract_before_a_new_row(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    get_diagnostics: Diagnostics,
) -> None:
    """The row in force ends tonight: the price changes at midnight in Paris."""
    freezer.move_to(paris(2026, 7, 31, 12, 0))
    entry = await setup_contract(hass, TariffOption.BASE)

    assert await get_diagnostics(entry) == {
        "entry": {
            "title": "Contract base 6 kVA",
            "version": 1,
            "data": {"option": "base", "power_kva": 6},
            "options": {},
        },
        "contract": {"option": "base", "power_kva": 6, "off_peak_hours": ""},
        "grid": {
            "downloaded_at": "2026-07-31T10:00:00+00:00",
            "trusted": True,
            "last_update_success": True,
            "rows": 4,
            "today": "2026-07-31",
            "powers_in_force_today": [6],
            "row_in_force": {
                "start": "2026-02-01",
                "end": "2026-07-31",
                "power_kva": 6,
                "subscription": "188.2",
                "prices": {"base": "0.194"},
            },
        },
        "now": {
            "utc": "2026-07-31T10:00:00+00:00",
            "paris": "2026-07-31T12:00:00+02:00",
            "period": "base",
            "price_key": "base",
            "price": "0.194",
            "next_price_change": "2026-08-01T00:00:00+02:00",
        },
        "tempo": None,
    }


async def test_hphc_contract_follows_off_peak_hours(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    get_diagnostics: Diagnostics,
) -> None:
    """Off-peak hours are shown in canonical text, with the price of the period."""
    freezer.move_to(paris(2026, 11, 11, 13, 30))
    entry = await setup_contract(
        hass, TariffOption.HPHC, off_peak="14:00-16:00, 1:00 - 7:00"
    )

    diagnostics = await get_diagnostics(entry)
    assert diagnostics["entry"]["options"] == {
        "off_peak_hours": "14:00-16:00, 1:00 - 7:00"
    }
    assert diagnostics["contract"] == {
        "option": "hphc",
        "power_kva": 6,
        "off_peak_hours": "01:00-07:00,14:00-16:00",
    }
    assert diagnostics["grid"]["rows"] == 3
    assert diagnostics["grid"]["powers_in_force_today"] == [6, 9]
    assert diagnostics["grid"]["row_in_force"] == {
        "start": "2026-08-01",
        "end": None,
        "power_kva": 6,
        "subscription": "190.8131821",
        "prices": {"peak": "0.2142", "off_peak": "0.1589"},
    }
    assert diagnostics["now"] == {
        "utc": "2026-11-11T12:30:00+00:00",
        "paris": "2026-11-11T13:30:00+01:00",
        "period": "peak",
        "price_key": "peak",
        "price": "0.2142",
        "next_price_change": "2026-11-11T14:00:00+01:00",
    }
    assert diagnostics["tempo"] is None

    await _at(hass, freezer, paris(2026, 11, 11, 14, 30))

    diagnostics = await get_diagnostics(entry)
    assert diagnostics["now"]["period"] == "off_peak"
    assert diagnostics["now"]["price_key"] == "off_peak"
    assert diagnostics["now"]["price"] == "0.1589"
    assert diagnostics["now"]["next_price_change"] == "2026-11-11T16:00:00+01:00"


async def test_tempo_contract_shows_the_known_colors(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    get_diagnostics: Diagnostics,
    hass_storage: dict[str, Any],
) -> None:
    """The known colors are sorted by day; the next refresh is the publication."""
    freezer.move_to(paris(2026, 11, 11, 7, 0))
    hass_storage[COLORS_STORAGE] = {
        "version": 1,
        "minor_version": 1,
        "key": COLORS_STORAGE,
        "data": {"2026-11-11": "red", "2026-11-09": "blue"},
    }
    source = FakeTempoSource({YESTERDAY: TempoColor.WHITE})
    entry = await setup_contract(hass, TariffOption.TEMPO, tempo=source)

    diagnostics = await get_diagnostics(entry)
    assert list(diagnostics["tempo"]["colors"].items()) == [
        ("2026-11-09", "blue"),
        ("2026-11-10", "white"),
        ("2026-11-11", "red"),
    ]
    assert diagnostics["tempo"]["last_update_success"] is True
    # Every expected color is known: the next one is published at 10:30.
    assert diagnostics["tempo"]["update_interval_seconds"] == 3.5 * 3600 + 2
    assert diagnostics["contract"]["off_peak_hours"] == ""
    assert diagnostics["now"] == {
        "utc": "2026-11-11T06:00:00+00:00",
        "paris": "2026-11-11T07:00:00+01:00",
        "period": "peak",
        "price_key": "red_peak",
        "price": "0.7295",
        "next_price_change": "2026-11-11T22:00:00+01:00",
    }


async def test_tempo_price_is_unknown_without_the_color_of_the_day(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    get_diagnostics: Diagnostics,
) -> None:
    """Without the color of the Tempo day, the row is known but not the price."""
    freezer.move_to(paris(2026, 11, 11, 7, 0))
    source = FakeTempoSource({YESTERDAY: TempoColor.WHITE})
    entry = await setup_contract(hass, TariffOption.TEMPO, tempo=source)

    diagnostics = await get_diagnostics(entry)
    assert diagnostics["tempo"] == {
        "colors": {"2026-11-10": "white"},
        "last_update_success": True,
        # The missing color of today is asked again 15 minutes later.
        "update_interval_seconds": 15 * 60 + 2,
    }
    assert diagnostics["grid"]["row_in_force"]["prices"]["blue_peak"] == "0.1654"
    assert diagnostics["now"]["period"] == "peak"
    assert diagnostics["now"]["price_key"] is None
    assert diagnostics["now"]["price"] is None
    assert TODAY.isoformat() not in diagnostics["tempo"]["colors"]


async def test_old_grid_is_not_trusted(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    get_diagnostics: Diagnostics,
) -> None:
    """After 7 days of failed downloads, the grid is kept but no price is given."""
    start = paris(2026, 11, 11, 12, 0)
    freezer.move_to(start)
    entry = await setup_contract(hass, TariffOption.HPHC, off_peak="22:00-06:00")

    with patch(COORDINATOR_FETCH, side_effect=CreConnectionError("offline")):
        await _at(hass, freezer, start + timedelta(days=1, minutes=1))
        await _at(hass, freezer, start + timedelta(days=7, minutes=2))

    diagnostics = await get_diagnostics(entry)
    assert diagnostics["grid"] == {
        "downloaded_at": "2026-11-11T11:00:00+00:00",
        "trusted": False,
        "last_update_success": False,
        "rows": 3,
        "today": "2026-11-18",
        "powers_in_force_today": [6, 9],
        "row_in_force": None,
    }
    assert diagnostics["now"] == {
        "utc": "2026-11-18T11:02:00+00:00",
        "paris": "2026-11-18T12:02:00+01:00",
        "period": "peak",
        "price_key": "peak",
        "price": None,
        "next_price_change": "2026-11-18T22:00:00+01:00",
    }


async def test_power_without_row(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    get_diagnostics: Diagnostics,
) -> None:
    """A power missing from the grid shows the powers in force instead."""
    freezer.move_to(paris(2026, 11, 11, 12, 0))
    entry = await setup_contract(hass, TariffOption.BASE, power=36)

    diagnostics = await get_diagnostics(entry)
    assert diagnostics["contract"]["power_kva"] == 36
    assert diagnostics["grid"]["trusted"] is True
    assert diagnostics["grid"]["powers_in_force_today"] == [3, 6, 9]
    assert diagnostics["grid"]["row_in_force"] is None
    assert diagnostics["now"]["price_key"] == "base"
    assert diagnostics["now"]["price"] is None
    assert diagnostics["now"]["next_price_change"] is None
