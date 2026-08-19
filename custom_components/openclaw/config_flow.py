"""Config flow for OpenClaw integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .const import (
    CONF_GATEWAY_URL,
    CONF_SESSION_KEY,
    CONF_SYSTEM_PROMPT,
    CONF_TOKEN,
    DEFAULT_CONVERSATION_NAME,
    DOMAIN,
)
from .gateway import OpenClawAuthError, OpenClawConnectionError, OpenClawGateway

_LOGGER = logging.getLogger(__name__)


async def _validate_gateway(hass: HomeAssistant, url: str, token: str) -> None:
    """Try connecting to the gateway to validate URL and credentials."""
    session = async_get_clientsession(hass)
    gateway = OpenClawGateway(url=url, token=token, session=session)
    try:
        await gateway.connect()
    finally:
        await gateway.disconnect()


def _connection_schema(
    default_url: str = "",
    default_token: str = "",
    default_session_key: str = "",
) -> vol.Schema:
    """Return the connection schema used in both initial setup and reconfigure."""
    return vol.Schema(
        {
            vol.Required(CONF_GATEWAY_URL, default=default_url): str,
            vol.Optional(CONF_TOKEN, default=default_token): str,
            vol.Required(CONF_SESSION_KEY, default=default_session_key): str,
        }
    )


class OpenClawConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OpenClaw."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Initial setup step — gateway URL, token, session key."""
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input[CONF_GATEWAY_URL].rstrip("/")
            token = user_input.get(CONF_TOKEN, "")
            session_key = user_input.get(CONF_SESSION_KEY, "")

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
                    options={CONF_SESSION_KEY: session_key},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_connection_schema(),
            errors=errors or None,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow editing gateway URL and token after initial setup."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input[CONF_GATEWAY_URL].rstrip("/")
            token = user_input.get(CONF_TOKEN, "")
            session_key = user_input.get(CONF_SESSION_KEY, "")

            try:
                await _validate_gateway(self.hass, url, token)
            except OpenClawAuthError:
                errors["base"] = "invalid_auth"
            except OpenClawConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception during OpenClaw reconfigure")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_GATEWAY_URL: url, CONF_TOKEN: token},
                    options_updates={CONF_SESSION_KEY: session_key},
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(
                default_url=entry.data.get(CONF_GATEWAY_URL, ""),
                default_token=entry.data.get(CONF_TOKEN, ""),
                default_session_key=entry.options.get(CONF_SESSION_KEY, ""),
            ),
            errors=errors or None,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return OpenClawOptionsFlow()


class OpenClawOptionsFlow(OptionsFlow):
    """Options flow — session key and system prompt, reconfigurable at any time."""

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
                ): TextSelector(
                    TextSelectorConfig(multiline=True, type=TextSelectorType.TEXT)
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
