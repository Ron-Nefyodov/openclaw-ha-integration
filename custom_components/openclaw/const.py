"""Constants for the OpenClaw integration."""

import logging

DOMAIN = "openclaw"
LOGGER = logging.getLogger(__package__)

CONF_GATEWAY_URL = "gateway_url"
CONF_TOKEN = "token"
CONF_SESSION_KEY = "session_key"
CONF_SYSTEM_PROMPT = "system_prompt"

DEFAULT_GATEWAY_URL = "ws://127.0.0.1:18789"
DEFAULT_CONVERSATION_NAME = "OpenClaw"

GATEWAY_PROTOCOL_VERSION = 4
GATEWAY_CLIENT_ID = "ha-openclaw"
GATEWAY_CLIENT_VERSION = "1.0.0"

# How long to wait for an assistant response before timing out
RESPONSE_TIMEOUT = 60.0
