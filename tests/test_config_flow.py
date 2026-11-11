"""Tests of the config flow and of the options flow."""

from __future__ import annotations

from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_USER, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.trve_edf.api import CreConnectionError, CreDataError
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
    paris,
    setup_contract,
)


@pytest.fixture(autouse=True)
def _now(freezer: FrozenDateTimeFactory) -> None:
    """Run the flows on a day of the current tariff period."""
    freezer.move_to(paris(2026, 11, 11, 12, 0))


async def _start(hass: HomeAssistant, option: TariffOption) -> ConfigFlowResult:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_OPTION: option.value}
    )


async def test_base_contract(hass: HomeAssistant) -> None:
    """A Base contract only needs its subscribed power."""
    with patch(CONFIG_FLOW_FETCH, return_value=BASE_GRID):
        result = await _start(hass, TariffOption.BASE)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "power"
    schema = result["data_schema"]
    assert schema is not None
    options = schema.schema[CONF_POWER].config["options"]
    assert options == [
        {"value": "3", "label": "3 kVA"},
        {"value": "6", "label": "6 kVA"},
        {"value": "9", "label": "9 kVA"},
    ]

    with patch(COORDINATOR_FETCH, return_value=BASE_GRID):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_POWER: "6"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Tarifs réglementés EDF \u2013 Base 6 kVA"
    assert result["data"] == {CONF_OPTION: "base", CONF_POWER: 6}
    assert result["options"] == {}


async def test_hphc_contract_with_off_peak_hours(hass: HomeAssistant) -> None:
    """An HP/HC contract asks for valid off-peak hours, stored canonically."""
    with patch(CONFIG_FLOW_FETCH, return_value=HPHC_GRID):
        result = await _start(hass, TariffOption.HPHC)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_POWER: "9"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "off_peak"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_OFF_PEAK_HOURS: "25:00-06:00"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_OFF_PEAK_HOURS: "off_peak_format"}

    with patch(COORDINATOR_FETCH, return_value=HPHC_GRID):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_OFF_PEAK_HOURS: " 22:00 - 6:00 "}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Tarifs réglementés EDF \u2013 HP/HC 9 kVA"
    assert result["data"] == {CONF_OPTION: "hphc", CONF_POWER: 9}
    assert result["options"] == {CONF_OFF_PEAK_HOURS: "22:00-06:00"}


async def test_tempo_contract(hass: HomeAssistant) -> None:
    """A Tempo contract needs its power only: its off-peak hours are fixed."""
    with patch(CONFIG_FLOW_FETCH, return_value=TEMPO_GRID):
        result = await _start(hass, TariffOption.TEMPO)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "power"
    schema = result["data_schema"]
    assert schema is not None
    assert [
        option["value"] for option in schema.schema[CONF_POWER].config["options"]
    ] == [
        "6",
        "9",
    ]

    with (
        patch(COORDINATOR_FETCH, return_value=TEMPO_GRID),
        patch(TEMPO_FETCH, FakeTempoSource()),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_POWER: "9"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Tarifs réglementés EDF \u2013 Tempo 9 kVA"
    assert result["data"] == {CONF_OPTION: "tempo", CONF_POWER: 9}
    assert result["options"] == {}


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (CreConnectionError("offline"), "cannot_connect"),
        (CreDataError("broken"), "invalid_data"),
    ],
)
async def test_grid_download_errors_can_be_retried(
    hass: HomeAssistant, side_effect: Exception, error: str
) -> None:
    """A failed download shows an error on the first step, which can be retried."""
    with patch(CONFIG_FLOW_FETCH, side_effect=side_effect):
        result = await _start(hass, TariffOption.BASE)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": error}

    with patch(CONFIG_FLOW_FETCH, return_value=BASE_GRID):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_OPTION: TariffOption.BASE.value}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "power"


async def test_no_power_in_force(hass: HomeAssistant) -> None:
    """A grid without any row in force cannot be used."""
    expired = TariffGrid(option=TariffOption.BASE, rows=BASE_GRID.rows[:1])
    with patch(CONFIG_FLOW_FETCH, return_value=expired):
        result = await _start(hass, TariffOption.BASE)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_power_available"


async def test_options_flow_changes_off_peak_hours(hass: HomeAssistant) -> None:
    """The off-peak hours of an HP/HC contract can be changed."""
    entry = await setup_contract(hass, TariffOption.HPHC, off_peak="22:00-06:00")

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_OFF_PEAK_HOURS: "nope"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_OFF_PEAK_HOURS: "off_peak_format"}

    with patch(COORDINATOR_FETCH, return_value=HPHC_GRID):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_OFF_PEAK_HOURS: "12:30-14:30, 1:30-7:30"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_OFF_PEAK_HOURS: "01:30-07:30,12:30-14:30"}


@pytest.mark.parametrize("option", [TariffOption.BASE, TariffOption.TEMPO])
async def test_base_and_tempo_contracts_have_no_options(
    hass: HomeAssistant, option: TariffOption
) -> None:
    """The options flow tells Base and Tempo contracts to use Reconfigure."""
    entry = await setup_contract(hass, option)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_options"


async def test_options_submitted_after_a_change_of_option(hass: HomeAssistant) -> None:
    """Off-peak hours are not written once the contract is not HP/HC anymore."""
    entry = await setup_contract(hass, TariffOption.HPHC, off_peak="22:00-06:00")
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    with patch(COORDINATOR_FETCH, return_value=BASE_GRID):
        hass.config_entries.async_update_entry(
            entry, data={CONF_OPTION: "base", CONF_POWER: 6}, options={}
        )
        await hass.async_block_till_done()
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_OFF_PEAK_HOURS: "01:00-07:00"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_options"
    assert entry.options == {}
