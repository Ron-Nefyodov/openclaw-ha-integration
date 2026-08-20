"""The OpenClaw integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_SSL,
    CONF_TOKEN,
    DOMAIN,
    LOGGER,
    SERVICE_RECONNECT,
    SERVICE_SET_SESSION,
)
from .gateway import OpenClawAuthError, OpenClawConnectionError, OpenClawGateway

PLATFORMS = (
    Platform.CONVERSATION,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type OpenClawConfigEntry = ConfigEntry[OpenClawGateway]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up OpenClaw."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: OpenClawConfigEntry) -> bool:
    """Set up OpenClaw from a config entry."""
    session = async_get_clientsession(hass)

    from .const import DEFAULT_PORT

    gateway = OpenClawGateway(
        host=entry.data[CONF_HOST],
        port=entry.data.get(CONF_PORT, DEFAULT_PORT),
        token=entry.data.get(CONF_TOKEN, ""),
        session=session,
        ssl=entry.data.get(CONF_SSL, False),
    )

    try:
        await gateway.start()
        # Wait briefly for the initial connect; if it fails the loop will retry
        import asyncio
        for _ in range(20):
            if gateway.connected:
                break
            await asyncio.sleep(0.5)
        if not gateway.connected:
            raise ConfigEntryNotReady("Could not connect to OpenClaw gateway")
    except OpenClawAuthError as err:
        LOGGER.error("OpenClaw authentication failed: %s", err)
        return False
    except ConfigEntryNotReady:
        raise
    except OpenClawConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = gateway

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    # ── Services ──────────────────────────────────────────────────────────────
    async def _service_reconnect(call: ServiceCall) -> None:
        """Force a reconnect to the gateway."""
        gw: OpenClawGateway = hass.data.get(DOMAIN, {}).get(
            call.data.get("config_entry_id", entry.entry_id), gateway
        )
        LOGGER.info("OpenClaw: manual reconnect requested")
        await gw.stop()
        await gw.start()

    async def _service_set_session(call: ServiceCall) -> None:
        """Update the active session key at runtime."""
        session_key: str = call.data["session_key"]
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, "session_key": session_key}
        )
        LOGGER.info("OpenClaw: session key updated to %s", session_key)

    if not hass.services.has_service(DOMAIN, SERVICE_RECONNECT):
        hass.services.async_register(DOMAIN, SERVICE_RECONNECT, _service_reconnect)

    if not hass.services.has_service(DOMAIN, SERVICE_SET_SESSION):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_SESSION,
            _service_set_session,
            schema=vol.Schema({vol.Required("session_key"): cv.string}),
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: OpenClawConfigEntry) -> bool:
    """Unload OpenClaw."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.stop()
    return unloaded


async def async_update_options(hass: HomeAssistant, entry: OpenClawConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
