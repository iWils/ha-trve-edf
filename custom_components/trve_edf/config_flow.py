"""Config flow of the EDF regulated tariffs (TRVE) integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .api import CreConnectionError, CreDataError, async_fetch_grid
from .const import (
    CONF_OFF_PEAK_HOURS,
    CONF_OPTION,
    CONF_POWER,
    DOMAIN,
    TITLE_PREFIX,
    TITLE_SEPARATOR,
)
from .models import TariffGrid, TariffOption
from .pricing import (
    PARIS,
    InvalidOffPeakRangesError,
    available_powers,
    format_off_peak_ranges,
    parse_off_peak_ranges,
)

OPTION_TITLES = {
    TariffOption.BASE: "Base",
    TariffOption.HPHC: "HP/HC",
}

OFF_PEAK_EXAMPLE = "22:00-06:00"


def _off_peak_schema(default: str | None) -> vol.Schema:
    key = (
        vol.Required(CONF_OFF_PEAK_HOURS)
        if default is None
        else vol.Required(CONF_OFF_PEAK_HOURS, default=default)
    )
    return vol.Schema({key: TextSelector()})


def _validate_off_peak(user_input: dict[str, Any]) -> tuple[str | None, dict[str, str]]:
    """Return the canonical off-peak hours, or the errors of the form."""
    try:
        ranges = parse_off_peak_ranges(user_input[CONF_OFF_PEAK_HOURS])
    except InvalidOffPeakRangesError:
        return None, {CONF_OFF_PEAK_HOURS: "invalid_off_peak_hours"}
    return format_off_peak_ranges(ranges), {}


class TrveEdfConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure a TRVE contract: option, subscribed power, off-peak hours."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._option = TariffOption.BASE
        self._grid: TariffGrid | None = None
        self._power = 0

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the tariff option, then download its grid."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._option = TariffOption(user_input[CONF_OPTION])
            try:
                self._grid = await async_fetch_grid(
                    async_get_clientsession(self.hass), self._option
                )
            except CreConnectionError:
                errors["base"] = "cannot_connect"
            except CreDataError:
                errors["base"] = "invalid_data"
            else:
                return await self.async_step_power()

        schema = vol.Schema(
            {
                vol.Required(CONF_OPTION): SelectSelector(
                    SelectSelectorConfig(
                        options=[option.value for option in TariffOption],
                        translation_key=CONF_OPTION,
                        mode=SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_power(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the subscribed power among those in force for the option."""
        assert self._grid is not None
        powers = available_powers(self._grid, dt_util.now(PARIS).date())
        if not powers:
            return self.async_abort(reason="no_power_available")

        if user_input is not None:
            self._power = int(user_input[CONF_POWER])
            if self._option is TariffOption.HPHC:
                return await self.async_step_off_peak()
            return self._async_create_contract(options={})

        schema = vol.Schema(
            {
                vol.Required(CONF_POWER): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=str(power), label=f"{power} kVA")
                            for power in powers
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="power", data_schema=schema)

    async def async_step_off_peak(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Enter the off-peak hours of an HP/HC contract."""
        errors: dict[str, str] = {}
        if user_input is not None:
            off_peak, errors = _validate_off_peak(user_input)
            if off_peak is not None:
                return self._async_create_contract(
                    options={CONF_OFF_PEAK_HOURS: off_peak}
                )

        default = None if user_input is None else user_input[CONF_OFF_PEAK_HOURS]
        return self.async_show_form(
            step_id="off_peak",
            data_schema=_off_peak_schema(default),
            errors=errors,
            description_placeholders={"example": OFF_PEAK_EXAMPLE},
        )

    @callback
    def _async_create_contract(self, options: dict[str, Any]) -> ConfigFlowResult:
        title = (
            f"{TITLE_PREFIX}{TITLE_SEPARATOR}"
            f"{OPTION_TITLES[self._option]} {self._power} kVA"
        )
        return self.async_create_entry(
            title=title,
            data={CONF_OPTION: self._option.value, CONF_POWER: self._power},
            options=options,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow of a contract."""
        return TrveEdfOptionsFlow()

    @classmethod
    @callback
    def async_supports_options_flow(cls, config_entry: ConfigEntry) -> bool:
        """Only HP/HC contracts have options: their off-peak hours."""
        return bool(config_entry.data[CONF_OPTION] == TariffOption.HPHC)


class TrveEdfOptionsFlow(OptionsFlow):
    """Change the off-peak hours of an HP/HC contract."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the off-peak hours."""
        errors: dict[str, str] = {}
        if user_input is not None:
            off_peak, errors = _validate_off_peak(user_input)
            if off_peak is not None:
                return self.async_create_entry(data={CONF_OFF_PEAK_HOURS: off_peak})
            default = user_input[CONF_OFF_PEAK_HOURS]
        else:
            default = self.config_entry.options[CONF_OFF_PEAK_HOURS]

        return self.async_show_form(
            step_id="init",
            data_schema=_off_peak_schema(default),
            errors=errors,
            description_placeholders={"example": OFF_PEAK_EXAMPLE},
        )
