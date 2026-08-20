"""Sensors for OpenClaw gateway diagnostics."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from . import OpenClawConfigEntry
from .const import DOMAIN, LOGGER
from .gateway import OpenClawError


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: OpenClawConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up gateway sensors using a coordinator."""
    gateway = config_entry.runtime_data

    coordinator = OpenClawStatusCoordinator(hass, gateway, config_entry.entry_id)
    # Schedule a background refresh without blocking setup
    config_entry.async_create_background_task(
        hass, coordinator.async_refresh(), "openclaw_initial_refresh"
    )

    async_add_entities(
        [
            OpenClawUptimeSensor(coordinator, config_entry),
            OpenClawClientCountSensor(coordinator, config_entry),
            OpenClawHealthSensor(coordinator, config_entry),
        ]
    )


class OpenClawStatusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetches gateway status on a regular interval."""

    def __init__(self, hass: HomeAssistant, gateway, entry_id: str) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=f"OpenClaw status ({entry_id})",
            update_interval=timedelta(seconds=60),
        )
        self._gateway = gateway

    async def _async_update_data(self) -> dict[str, Any]:
        if not self._gateway.connected:
            raise UpdateFailed("Gateway not connected")
        try:
            status = await self._gateway.get_status()
            health = await self._gateway.get_health()
            return {"status": status, "health": health}
        except OpenClawError as err:
            raise UpdateFailed(str(err)) from err


class _BaseGatewaySensor(CoordinatorEntity[OpenClawStatusCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: OpenClawStatusCoordinator,
        entry: OpenClawConfigEntry,
        unique_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{unique_suffix}"
        from homeassistant.helpers import device_registry as dr

        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="OpenClaw",
            model="Local AI Agent",
            entry_type=dr.DeviceEntryType.SERVICE,
        )


class OpenClawUptimeSensor(_BaseGatewaySensor):
    _attr_name = "Gateway Uptime"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "uptime")

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("status", {}).get("uptime")


class OpenClawClientCountSensor(_BaseGatewaySensor):
    _attr_name = "Connected Clients"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:account-group"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "client_count")

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        clients = (
            self.coordinator.data.get("status", {}).get("clients")
            or self.coordinator.data.get("status", {}).get("connectedClients")
        )
        if isinstance(clients, list):
            return len(clients)
        if isinstance(clients, int):
            return clients
        return None


class OpenClawHealthSensor(_BaseGatewaySensor):
    _attr_name = "Gateway Health"
    _attr_icon = "mdi:heart-pulse"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "health")

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None:
            return None
        health = self.coordinator.data.get("health", {})
        return health.get("status") or health.get("state") or "unknown"
