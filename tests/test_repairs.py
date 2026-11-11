"""Tests of the repair issue of a subscribed power missing from the grid."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import logging
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.trve_edf.const import DOMAIN
from custom_components.trve_edf.models import PriceKey, TariffGrid, TariffOption

from .common import BASE_GRID, COORDINATOR_FETCH, paris, setup_contract, state


async def test_power_missing_from_the_grid_raises_an_issue(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A power without tariff in force raises an issue, removed with the contract."""
    freezer.move_to(paris(2026, 11, 11, 12, 0))
    entry = await setup_contract(hass, TariffOption.BASE, power=36)
    issue_id = f"power_not_available_{entry.entry_id}"

    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_key == "power_not_available"
    assert issue.translation_placeholders == {"title": entry.title, "power": "36"}
    assert issue.severity is ir.IssueSeverity.ERROR

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_no_issue_when_the_power_is_in_the_grid(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A power with a tariff in force raises no issue, and clears an old one."""
    freezer.move_to(paris(2026, 11, 11, 12, 0))
    entry = await setup_contract(hass, TariffOption.BASE, power=6)
    issue_id = f"power_not_available_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None

    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="power_not_available",
    )
    entry.runtime_data.async_update_listeners()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_nothing_is_decided_with_an_untrusted_grid(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A grid too old to be trusted neither raises nor clears the issue."""
    freezer.move_to(paris(2026, 11, 11, 12, 0))
    entry = await setup_contract(hass, TariffOption.BASE, power=36)
    issue_id = f"power_not_available_{entry.entry_id}"
    ir.async_delete_issue(hass, DOMAIN, issue_id)

    coordinator = entry.runtime_data
    coordinator.grid_downloaded_at = paris(2026, 11, 1, 12, 0)
    coordinator.async_update_listeners()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None

    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="power_not_available",
    )
    coordinator.async_update_listeners()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None


async def test_conflicting_rows_are_logged_without_issue(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Conflicting rows make prices unavailable, but the power is offered."""
    freezer.move_to(paris(2026, 11, 11, 12, 0))
    erratum = replace(BASE_GRID.rows[2], prices={PriceKey.BASE: Decimal("0.3000")})
    grid = TariffGrid(option=TariffOption.BASE, rows=(*BASE_GRID.rows, erratum))
    entry = MockConfigEntry(
        domain=DOMAIN, title="Base 6 kVA", data={"option": "base", "power_kva": 6}
    )
    entry.add_to_hass(hass)
    with patch(COORDINATOR_FETCH, return_value=grid), caplog.at_level(logging.WARNING):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entry.runtime_data.async_update_listeners()

    issue_id = f"power_not_available_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert caplog.text.count("conflicting rows") == 1
    assert state(hass, entry, "current_price").state == STATE_UNAVAILABLE


async def test_unloading_removes_the_issue(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A disabled or unloaded contract does not keep its repair issue."""
    freezer.move_to(paris(2026, 11, 11, 12, 0))
    entry = await setup_contract(hass, TariffOption.BASE, power=36)
    issue_id = f"power_not_available_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
