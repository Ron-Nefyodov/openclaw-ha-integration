"""Conversation support for OpenClaw."""

from __future__ import annotations

import uuid
from typing import Literal

from homeassistant.components import conversation
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OpenClawConfigEntry
from .const import CONF_SESSION_KEY, CONF_SYSTEM_PROMPT, DOMAIN, LOGGER
from .gateway import OpenClawError, OpenClawTimeoutError


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: OpenClawConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up OpenClaw conversation entity."""
    async_add_entities([OpenClawConversationEntity(config_entry)])


class OpenClawConversationEntity(conversation.ConversationEntity):
    """OpenClaw conversation agent."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry: OpenClawConfigEntry) -> None:
        self.entry = entry
        self._attr_unique_id = entry.entry_id
        from homeassistant.helpers import device_registry as dr

        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="OpenClaw",
            model="Local AI Agent",
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        return MATCH_ALL

    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        """Forward user message to OpenClaw and return the response."""
        options = self.entry.options
        system_prompt = options.get(CONF_SYSTEM_PROMPT, "")

        text = user_input.text
        if system_prompt:
            text = f"{system_prompt}\n\n{text}"

        gateway = self.entry.runtime_data
        session_key = await gateway.ensure_session(options.get(CONF_SESSION_KEY, ""))

        try:
            response_text = await gateway.send_message(session_key=session_key, text=text)
        except OpenClawTimeoutError:
            LOGGER.warning("OpenClaw did not respond within the timeout")
            intent_response = intent.IntentResponse(language=user_input.language)
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.NO_INTENT_MATCH,
                "OpenClaw did not respond in time. Is the session active?",
            )
            return conversation.ConversationResult(
                response=intent_response,
                conversation_id=user_input.conversation_id or str(uuid.uuid4()),
            )
        except OpenClawError as err:
            LOGGER.error("OpenClaw error: %s", err)
            intent_response = intent.IntentResponse(language=user_input.language)
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                f"OpenClaw error: {err}",
            )
            return conversation.ConversationResult(
                response=intent_response,
                conversation_id=user_input.conversation_id or str(uuid.uuid4()),
            )

        intent_response = intent.IntentResponse(language=user_input.language)
        intent_response.async_set_speech(response_text)
        return conversation.ConversationResult(
            response=intent_response,
            conversation_id=user_input.conversation_id or str(uuid.uuid4()),
        )
