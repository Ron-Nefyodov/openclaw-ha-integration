"""The OpenClaw integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import CONF_GATEWAY_URL, CONF_TOKEN, DOMAIN, LOGGER
from .gateway import OpenClawAuthError, OpenClawConnectionError, OpenClawGateway

PLATFORMS = (Platform.CONVERSATION,)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type OpenClawConfigEntry = ConfigEntry[OpenClawGateway]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up OpenClaw."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: OpenClawConfigEntry) -> bool:
    """Set up OpenClaw from a config entry."""
    session = async_get_clientsession(hass)
    gateway = OpenClawGateway(
        url=entry.data[CONF_GATEWAY_URL],
        token=entry.data.get(CONF_TOKEN, ""),
        session=session,
    )

    try:
        await gateway.connect()
    except OpenClawAuthError as err:
        LOGGER.error("OpenClaw authentication failed: %s", err)
        return False
    except OpenClawConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = gateway

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: OpenClawConfigEntry) -> bool:
    """Unload OpenClaw."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.disconnect()
    return unloaded


async def async_update_options(hass: HomeAssistant, entry: OpenClawConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
