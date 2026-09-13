"""Config flow for Steward."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

from .const import (
    CONF_ALLOW_DESTRUCTIVE,
    CONF_ALLOW_WRITE,
    CONF_RATE_LIMIT,
    CONF_RATE_WINDOW,
    CONF_REQUIRE_ADMIN,
    DEFAULT_ALLOW_DESTRUCTIVE,
    DEFAULT_ALLOW_WRITE,
    DEFAULT_RATE_LIMIT,
    DEFAULT_RATE_WINDOW,
    DEFAULT_REQUIRE_ADMIN,
    DOMAIN,
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_ALLOW_WRITE, default=DEFAULT_ALLOW_WRITE): bool,
        vol.Optional(CONF_ALLOW_DESTRUCTIVE, default=DEFAULT_ALLOW_DESTRUCTIVE): bool,
        vol.Optional(CONF_REQUIRE_ADMIN, default=DEFAULT_REQUIRE_ADMIN): bool,
        vol.Optional(CONF_RATE_LIMIT, default=DEFAULT_RATE_LIMIT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=10000)
        ),
        vol.Optional(CONF_RATE_WINDOW, default=DEFAULT_RATE_WINDOW): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=3600)
        ),
    }
)


class StewardConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """One instance is enough; the endpoint is a single path."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=OPTIONS_SCHEMA)

        return self.async_create_entry(title="Steward", data={}, options=user_input)

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return StewardOptionsFlow()


class StewardOptionsFlow(OptionsFlow):
    """Change permissions after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )
