"""Binary sensor: OpenClaw gateway connectivity."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OpenClawConfigEntry
from .const import DOMAIN, LOGGER


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: OpenClawConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the gateway connectivity binary sensor."""
    gateway = config_entry.runtime_data
    async_add_entities([OpenClawConnectivitySensor(config_entry, gateway)])


class OpenClawConnectivitySensor(BinarySensorEntity):
    """Tracks whether the gateway WebSocket is connected."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_name = "Gateway Connected"
    _attr_should_poll = False

    def __init__(self, entry: OpenClawConfigEntry, gateway) -> None:
        self._gateway = gateway
        self._attr_unique_id = f"{entry.entry_id}_connected"
        from homeassistant.helpers import device_registry as dr

        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="OpenClaw",
            model="Local AI Agent",
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool:
        return self._gateway.connected

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_connect() -> None:
            self._attr_is_on = True
            self.async_write_ha_state()

        @callback
        def _on_disconnect() -> None:
            self._attr_is_on = False
            self.async_write_ha_state()

        self._gateway.add_connected_listener(_on_connect)
        self._gateway.add_disconnected_listener(_on_disconnect)
