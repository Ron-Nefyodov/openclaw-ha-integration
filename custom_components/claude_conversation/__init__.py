"""The Claude Conversation integration."""

from __future__ import annotations

from functools import partial

import anthropic

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_CHAT_MODEL,
    DEFAULT_CONVERSATION_NAME,
    DOMAIN,
    LOGGER,
    RECOMMENDED_CHAT_MODEL,
)

PLATFORMS = (Platform.CONVERSATION,)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type ClaudeConfigEntry = ConfigEntry[anthropic.AsyncAnthropic]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up Claude Conversation."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ClaudeConfigEntry) -> bool:
    """Set up Claude Conversation from a config entry."""
    client = await hass.async_add_executor_job(
        partial(anthropic.AsyncAnthropic, api_key=entry.data[CONF_API_KEY])
    )
    try:
        subentries = list(entry.subentries.values())
        if subentries:
            model_id = subentries[0].data.get(CONF_CHAT_MODEL, RECOMMENDED_CHAT_MODEL)
        else:
            model_id = RECOMMENDED_CHAT_MODEL
        model = await client.models.retrieve(model_id=model_id, timeout=10.0)
        LOGGER.debug("Claude model: %s", model.display_name)
    except anthropic.AuthenticationError as err:
        LOGGER.error("Invalid API key: %s", err)
        return False
    except anthropic.AnthropicError as err:
        raise ConfigEntryNotReady(err) from err

    entry.runtime_data = client

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Claude Conversation."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_update_options(hass: HomeAssistant, entry: ClaudeConfigEntry) -> None:
    """Update options."""
    await hass.config_entries.async_reload(entry.entry_id)
