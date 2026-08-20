"""Config flow for OpenClaw integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_SESSION_KEY,
    CONF_SSL,
    CONF_SYSTEM_PROMPT,
    CONF_TOKEN,
    DEFAULT_CONVERSATION_NAME,
    DEFAULT_PORT,
    DOMAIN,
)
from .gateway import OpenClawAuthError, OpenClawConnectionError, OpenClawGateway

_LOGGER = logging.getLogger(__name__)


async def _validate_gateway(
    hass: HomeAssistant, host: str, port: int, token: str, ssl: bool
) -> None:
    """Try connecting to validate the configuration."""
    session = async_get_clientsession(hass)
    gateway = OpenClawGateway(host=host, port=port, token=token, session=session, ssl=ssl)
    try:
        await gateway.start()
        for _ in range(20):
            if gateway.connected:
                break
            await asyncio.sleep(0.25)
        if not gateway.connected:
            raise OpenClawConnectionError("Connection timed out")
    finally:
        await gateway.stop()


def _connection_schema(
    default_host: str = "",
    default_port: int = DEFAULT_PORT,
    default_token: str = "",
    default_ssl: bool = False,
    default_session_key: str = "",
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=default_host): str,
            vol.Optional(CONF_PORT, default=default_port): NumberSelector(
                NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_TOKEN, default=default_token): str,
            vol.Optional(CONF_SSL, default=default_ssl): BooleanSelector(),
            vol.Optional(CONF_SESSION_KEY, default=default_session_key): str,
        }
    )


class OpenClawConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OpenClaw."""

    VERSION = 2
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input.get(CONF_PORT, DEFAULT_PORT))
            token = user_input.get(CONF_TOKEN, "").strip()
            ssl = user_input.get(CONF_SSL, False)
            session_key = user_input.get(CONF_SESSION_KEY, "").strip()

            try:
                await _validate_gateway(self.hass, host, port, token, ssl)
            except OpenClawAuthError:
                errors["base"] = "invalid_auth"
            except OpenClawConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during OpenClaw setup")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(f"{host}:{port}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=DEFAULT_CONVERSATION_NAME,
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_TOKEN: token,
                        CONF_SSL: ssl,
                    },
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
        """Allow editing connection details after initial setup."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input.get(CONF_PORT, DEFAULT_PORT))
            token = user_input.get(CONF_TOKEN, "").strip()
            ssl = user_input.get(CONF_SSL, False)
            session_key = user_input.get(CONF_SESSION_KEY, "").strip()

            try:
                await _validate_gateway(self.hass, host, port, token, ssl)
            except OpenClawAuthError:
                errors["base"] = "invalid_auth"
            except OpenClawConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during OpenClaw reconfigure")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_TOKEN: token,
                        CONF_SSL: ssl,
                    },
                    options_updates={CONF_SESSION_KEY: session_key},
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(
                default_host=entry.data.get(CONF_HOST, ""),
                default_port=entry.data.get(CONF_PORT, DEFAULT_PORT),
                default_token=entry.data.get(CONF_TOKEN, ""),
                default_ssl=entry.data.get(CONF_SSL, False),
                default_session_key=entry.options.get(CONF_SESSION_KEY, ""),
            ),
            errors=errors or None,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return OpenClawOptionsFlow()


class OpenClawOptionsFlow(OptionsFlow):
    """Options — session key, system prompt."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        schema = vol.Schema(
            {
                vol.Optional(
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
