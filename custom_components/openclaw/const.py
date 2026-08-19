"""Constants for the OpenClaw integration."""

import logging

DOMAIN = "openclaw"
LOGGER = logging.getLogger(__package__)

CONF_GATEWAY_URL = "gateway_url"
CONF_TOKEN = "token"
CONF_SESSION_KEY = "session_key"
CONF_SYSTEM_PROMPT = "system_prompt"

DEFAULT_GATEWAY_URL = ""  # User must supply the gateway IP (e.g. ws://192.168.1.x:18789)
DEFAULT_CONVERSATION_NAME = "OpenClaw"

GATEWAY_PROTOCOL_VERSION = 3
# client.id and client.mode must be values from the gateway's closed enum registries.
# See packages/gateway-protocol/src/client-info.ts in the OpenClaw source.
GATEWAY_CLIENT_ID = "cli"
GATEWAY_CLIENT_MODE = "cli"
GATEWAY_CLIENT_VERSION = "1.0.0"

# How long to wait for an assistant response before timing out
RESPONSE_TIMEOUT = 60.0
