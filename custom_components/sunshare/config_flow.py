"""Config flow for the Sunshare integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .api import SunshareApiClient, SunshareApiError, SunshareAuthError
from .const import CONF_USER_ACCOUNT, DEFAULT_SCAN_INTERVAL, DOMAIN, MIN_SCAN_INTERVAL

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USER_ACCOUNT): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class SunshareConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Sunshare."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        errors: dict[str, str] = {}
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = SunshareApiClient(
                session, user_input[CONF_USER_ACCOUNT], user_input[CONF_PASSWORD]
            )
            try:
                await client.async_login()
            except SunshareAuthError:
                errors["base"] = "invalid_auth"
            except SunshareApiError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(user_input[CONF_USER_ACCOUNT].lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_USER_ACCOUNT], data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SunshareOptionsFlow()


class SunshareOptionsFlow(OptionsFlow):
    """Lets the user tune the polling interval.

    Single-session-per-account (API_DOCUMENTATION.md §2) and unknown
    rate-limit behaviour mean a conservative default matters — this is kept
    user-adjustable rather than hardcoded.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                    cv.positive_int, vol.Range(min=MIN_SCAN_INTERVAL)
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
