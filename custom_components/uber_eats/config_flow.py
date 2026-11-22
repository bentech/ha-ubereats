"""Config flow for Uber Eats."""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    ACTIVE_ORDERS_ID,
    CONF_COOKIE,
    CONF_LOCALE,
    CONF_TIMEZONE,
    DEFAULT_LOCALE,
    DEFAULT_TIMEZONE,
    DOMAIN,
)


class UberEatsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Connect a browser session to track active Uber Eats orders."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the browser cookie and regional settings."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_COOKIE].strip():
                errors[CONF_COOKIE] = "invalid_cookie"
            try:
                ZoneInfo(user_input[CONF_TIMEZONE])
            except (ValueError, ZoneInfoNotFoundError):
                errors[CONF_TIMEZONE] = "invalid_timezone"
            if not errors:
                await self.async_set_unique_id(ACTIVE_ORDERS_ID)
                self._abort_if_unique_id_configured()
                data = {
                    **user_input,
                    CONF_COOKIE: user_input[CONF_COOKIE].strip(),
                }
                return self.async_create_entry(title="Uber Eats", data=data)

        schema = vol.Schema(
            {
                vol.Required(CONF_COOKIE): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Required(CONF_TIMEZONE, default=DEFAULT_TIMEZONE): str,
                vol.Required(CONF_LOCALE, default=DEFAULT_LOCALE): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Ask for a replacement for the rejected session."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Replace the browser session and reload this order."""
        errors = {}
        if user_input is not None:
            cookie = user_input[CONF_COOKIE].strip()
            if cookie:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data_updates={CONF_COOKIE: cookie}
                )
            errors[CONF_COOKIE] = "invalid_cookie"
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_COOKIE): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )
