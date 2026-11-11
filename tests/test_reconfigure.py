"""Tests of the reconfiguration of a contract."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_RECONFIGURE, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.trve_edf.api import CreConnectionError
from custom_components.trve_edf.const import (
    CONF_OFF_PEAK_HOURS,
    CONF_OPTION,
    CONF_POWER,
    DOMAIN,
)
from custom_components.trve_edf.models import TariffGrid, TariffOption

from .common import (
    BASE_GRID,
    CONFIG_FLOW_FETCH,
    COORDINATOR_FETCH,
    HPHC_GRID,
    TEMPO_FETCH,
    TEMPO_GRID,
    FakeTempoSource,
    entity_id,
    paris,
    setup_contract,
    state,
)


@pytest.fixture(autouse=True)
def _now(freezer: FrozenDateTimeFactory) -> None:
    """Run the flows on a day of the current tariff period, in peak hours."""
    freezer.move_to(paris(2026, 11, 11, 12, 0))


def suggested(result: Any, key: str) -> Any:
    """Return the suggested value of a field of a form."""
    for field in result["data_schema"].schema:
        if field == key:
            return (field.description or {}).get("suggested_value")
    raise AssertionError(f"no {key} field")


async def start(hass: HomeAssistant, entry: MockConfigEntry) -> Any:
    """Start the reconfiguration of a contract."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )


async def test_from_hphc_to_tempo(hass: HomeAssistant) -> None:
    """A contract changes option; the sensors of the former option are removed."""
    entry = await setup_contract(hass, TariffOption.HPHC, off_peak="22:00-06:00")
    assert entity_id(hass, entry, "peak_price") is not None

    result = await start(hass, entry)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert suggested(result, CONF_OPTION) == "hphc"

    with patch(CONFIG_FLOW_FETCH, return_value=TEMPO_GRID):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_OPTION: "tempo"}
        )
    assert result["step_id"] == "power"
    assert suggested(result, CONF_POWER) is None

    with (
        patch(COORDINATOR_FETCH, return_value=TEMPO_GRID),
        patch(TEMPO_FETCH, FakeTempoSource()),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_POWER: "9"}
        )
        await hass.async_block_till_done(wait_background_tasks=True)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {CONF_OPTION: "tempo", CONF_POWER: 9}
    assert entry.options == {}
    # The title chosen when the contract was added is kept.
    assert entry.title == "Contract hphc 6 kVA"
    assert entry.state is ConfigEntryState.LOADED
    assert entity_id(hass, entry, "peak_price") is None
    assert state(hass, entry, "red_peak_price").state == "0.7295"


async def test_off_peak_hours_of_an_hphc_contract(hass: HomeAssistant) -> None:
    """The same option and power are suggested, then the current off-peak hours."""
    entry = await setup_contract(hass, TariffOption.HPHC, off_peak="22:00-06:00")
    assert state(hass, entry, "current_period").state == "peak"

    result = await start(hass, entry)
    with patch(CONFIG_FLOW_FETCH, return_value=HPHC_GRID):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_OPTION: "hphc"}
        )
    assert suggested(result, CONF_POWER) == "6"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_POWER: "6"}
    )
    assert result["step_id"] == "off_peak"
    schema = result["data_schema"]
    assert schema is not None
    off_peak_field = next(
        field for field in schema.schema if field == CONF_OFF_PEAK_HOURS
    )
    assert off_peak_field.default() == "22:00-06:00"

    with patch(COORDINATOR_FETCH, return_value=HPHC_GRID):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_OFF_PEAK_HOURS: "11:00-13:00,22:00-06:00"}
        )
        await hass.async_block_till_done(wait_background_tasks=True)

    assert result["reason"] == "reconfigure_successful"
    assert entry.options == {CONF_OFF_PEAK_HOURS: "11:00-13:00,22:00-06:00"}
    assert state(hass, entry, "current_period").state == "off_peak"


async def test_a_contract_waiting_for_its_setup_is_reloaded(
    hass: HomeAssistant,
) -> None:
    """A contract that could not be set up is reloaded after its reconfiguration."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Base 6 kVA",
        data={CONF_OPTION: "hphc", CONF_POWER: 6},
        options={CONF_OFF_PEAK_HOURS: "22:00-06:00"},
    )
    entry.add_to_hass(hass)
    with patch(COORDINATOR_FETCH, side_effect=CreConnectionError("offline")):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY

    result = await start(hass, entry)
    with patch(CONFIG_FLOW_FETCH, return_value=HPHC_GRID):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_OPTION: "hphc"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_POWER: "9"}
        )
    with patch(COORDINATOR_FETCH, return_value=HPHC_GRID):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_OFF_PEAK_HOURS: "22:00-06:00"}
        )
        await hass.async_block_till_done(wait_background_tasks=True)

    assert result["reason"] == "reconfigure_successful"
    reloaded = hass.config_entries.async_get_entry(entry.entry_id)
    assert reloaded is not None
    assert reloaded.data[CONF_POWER] == 9
    assert reloaded.state is ConfigEntryState.LOADED


async def test_a_generated_title_follows_the_contract(hass: HomeAssistant) -> None:
    """A generated title is updated; the off-peak hours are asked for HP/HC."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tarifs réglementés EDF \u2013 Base 6 kVA",
        data={CONF_OPTION: "base", CONF_POWER: 6},
    )
    entry.add_to_hass(hass)
    with patch(COORDINATOR_FETCH, return_value=BASE_GRID):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await start(hass, entry)
    with patch(CONFIG_FLOW_FETCH, return_value=HPHC_GRID):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_OPTION: "hphc"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_POWER: "9"}
        )
    assert result["step_id"] == "off_peak"
    schema = result["data_schema"]
    assert schema is not None
    off_peak_field = next(
        field for field in schema.schema if field == CONF_OFF_PEAK_HOURS
    )
    assert off_peak_field.default is vol.UNDEFINED

    with patch(COORDINATOR_FETCH, return_value=HPHC_GRID):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_OFF_PEAK_HOURS: "22:00-06:00"}
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert entry.title == "Tarifs réglementés EDF \u2013 HP/HC 9 kVA"
    assert entry.options == {CONF_OFF_PEAK_HOURS: "22:00-06:00"}
    assert entity_id(hass, entry, "base_price") is None


async def test_reconfiguring_the_power_clears_the_repair_issue(
    hass: HomeAssistant,
) -> None:
    """Choosing a power with a tariff in force clears its repair issue."""
    entry = await setup_contract(hass, TariffOption.BASE, power=36)
    issue_id = f"power_not_available_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    result = await start(hass, entry)
    with patch(CONFIG_FLOW_FETCH, return_value=BASE_GRID):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_OPTION: "base"}
        )
    assert suggested(result, CONF_POWER) is None
    with patch(COORDINATOR_FETCH, return_value=BASE_GRID):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_POWER: "6"}
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_reconfigure_errors(hass: HomeAssistant) -> None:
    """A failed download can be retried; a grid without power aborts."""
    entry = await setup_contract(hass, TariffOption.BASE)
    result = await start(hass, entry)

    with patch(CONFIG_FLOW_FETCH, side_effect=CreConnectionError("offline")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_OPTION: "base"}
        )
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "cannot_connect"}

    expired = TariffGrid(option=TariffOption.BASE, rows=BASE_GRID.rows[:1])
    with patch(CONFIG_FLOW_FETCH, return_value=expired):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_OPTION: "base"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_power_available"
