"""Diagnostics for the OpenClaw integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import OpenClawConfigEntry
from .const import CONF_TOKEN

TO_REDACT = {CONF_TOKEN, "token", "auth"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: OpenClawConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the config entry."""
    gateway = entry.runtime_data

    status: dict[str, Any] = {}
    health: dict[str, Any] = {}
    if gateway.connected:
        try:
            status = await gateway.get_status()
            health = await gateway.get_health()
        except Exception as err:
            status = {"error": str(err)}

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "gateway": {
            "connected": gateway.connected,
            "status": status,
            "health": health,
        },
    }
