"""Tests of the config flow."""

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.trve_edf.const import DOMAIN


async def test_user_flow_is_not_available_yet(hass: HomeAssistant) -> None:
    """Until version 0.1.0, the user flow explains that it is not available."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_available_yet"
