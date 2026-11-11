"""Config flow of the EDF regulated tariffs (TRVE) integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class TrveEdfConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure a TRVE contract."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow started by the user.

        The configuration steps arrive with version 0.1.0.
        """
        return self.async_abort(reason="not_available_yet")
