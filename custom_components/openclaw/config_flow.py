"""Config flow for OpenClaw integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .const import (
    CONF_GATEWAY_URL,
    CONF_SESSION_KEY,
    CONF_SYSTEM_PROMPT,
    CONF_TOKEN,
    DEFAULT_CONVERSATION_NAME,
    DEFAULT_GATEWAY_URL,
    DOMAIN,
)
from .gateway import OpenClawAuthError, OpenClawConnectionError, OpenClawGateway

_LOGGER = logging.getLogger(__name__)


async def _validate_gateway(hass: HomeAssistant, url: str, token: str) -> None:
    """Try connecting to the gateway to validate credentials."""
    session = async_get_clientsession(hass)
    gateway = OpenClawGateway(url=url, token=token, session=session)
    try:
        await gateway.connect()
    finally:
        await gateway.disconnect()


class OpenClawConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OpenClaw."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input[CONF_GATEWAY_URL].rstrip("/")
            token = user_input.get(CONF_TOKEN, "")

            try:
                await _validate_gateway(self.hass, url, token)
            except OpenClawAuthError:
                errors["base"] = "invalid_auth"
            except OpenClawConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception during OpenClaw setup")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=DEFAULT_CONVERSATION_NAME,
                    data={CONF_GATEWAY_URL: url, CONF_TOKEN: token},
                    options={CONF_SESSION_KEY: user_input.get(CONF_SESSION_KEY, "")},
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_GATEWAY_URL, default=DEFAULT_GATEWAY_URL): str,
                vol.Optional(CONF_TOKEN, default=""): str,
                vol.Required(CONF_SESSION_KEY): str,
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors or None
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow."""
        return OpenClawOptionsFlow()


class OpenClawOptionsFlow(OptionsFlow):
    """Handle options for OpenClaw."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SESSION_KEY,
                    default=self.config_entry.options.get(CONF_SESSION_KEY, ""),
                ): str,
                vol.Optional(
                    CONF_SYSTEM_PROMPT,
                    default=self.config_entry.options.get(CONF_SYSTEM_PROMPT, ""),
                ): TextSelector(TextSelectorConfig(multiline=True, type=TextSelectorType.TEXT)),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
