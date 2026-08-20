"""Constants for the OpenClaw integration."""

import logging

DOMAIN = "openclaw"
LOGGER = logging.getLogger(__package__)

# ── Config entry keys ──────────────────────────────────────────────────────────
CONF_HOST = "host"
CONF_PORT = "port"
CONF_TOKEN = "token"
CONF_SSL = "ssl"
CONF_SESSION_KEY = "session_key"
CONF_SYSTEM_PROMPT = "system_prompt"
CONF_MODEL = "model"
CONF_THINKING = "thinking"
CONF_STRIP_EMOJIS = "strip_emojis"
CONF_TIMEOUT = "timeout"

DEFAULT_HOST = ""
DEFAULT_PORT = 18789
DEFAULT_CONVERSATION_NAME = "OpenClaw"
DEFAULT_TIMEOUT = 60

# ── Gateway WebSocket protocol ─────────────────────────────────────────────────
# client.id and client.mode are closed enums in the gateway protocol.
# Source: packages/gateway-protocol/src/client-info.ts
PROTOCOL_MIN_VERSION = 3
PROTOCOL_MAX_VERSION = 4

CLIENT_ID = "gateway-client"       # valid GatewayClientId
CLIENT_MODE = "backend"            # valid GatewayClientMode
CLIENT_PLATFORM = "python"
CLIENT_DISPLAY_NAME = "Home Assistant OpenClaw"
CLIENT_VERSION = "1.0.0"

DEVICE_ROLE = "operator"
DEVICE_SCOPES = ["operator.read", "operator.write"]

# Seconds to wait for the challenge event before falling back to legacy auth
CHALLENGE_TIMEOUT = 2.0

# ── Connection lifecycle ───────────────────────────────────────────────────────
RECONNECT_DELAY = 5          # seconds between reconnect attempts
HEARTBEAT_INTERVAL = 30      # seconds between ping frames
REQUEST_TIMEOUT = 15         # seconds for a single RPC call

# ── Response ───────────────────────────────────────────────────────────────────
RESPONSE_TIMEOUT = 60.0      # seconds waiting for assistant reply

# ── Services ───────────────────────────────────────────────────────────────────
SERVICE_RECONNECT = "reconnect"
SERVICE_SET_SESSION = "set_session"

# ── Storage ────────────────────────────────────────────────────────────────────
STORAGE_KEY_DEVICE = f"{DOMAIN}_device_keypair"
STORAGE_VERSION = 1
