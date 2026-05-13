"""Diagnostic sensor for Haylou LS02 watch connection state."""

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL, CONF_DEVICE_ADDRESS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up diagnostic sensor for Haylou LS02."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    device_address = config_entry.data[CONF_DEVICE_ADDRESS]
    device_name = config_entry.data.get(CONF_NAME, "Haylou Watch")

    entity = HaylouConnectionStateSensor(
        coordinator, device_address, device_name, config_entry
    )
    async_add_entities([entity])


class HaylouConnectionStateSensor(CoordinatorEntity, SensorEntity):
    """Represent Haylou watch connection state as a diagnostic sensor."""

    _attr_icon = "mdi:bluetooth"
    _attr_should_poll = False
    _attr_entity_category = "diagnostic"

    def __init__(self, coordinator, device_address: str, device_name: str, config_entry: ConfigEntry):
        """Initialize the diagnostic sensor."""
        super().__init__(coordinator)
        self.device_address = device_address
        self.device_name = device_name
        self.config_entry = config_entry
        self._attr_unique_id = f"{DOMAIN}_{device_address}_connection_state"
        self._attr_name = f"{device_name} Connection State"
        self._attr_entity_id = f"sensor.haylou_ls02_connection_state_{device_address.replace(':', '')}"

    @property
    def native_value(self) -> str:
        """Return the connection state."""
        return self.coordinator.data.get("connection_state", "disconnected")

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information for the Haylou watch."""
        return {
            "identifiers": {(DOMAIN, self.device_address)},
            "name": self.device_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
        }

    async def async_added_to_hass(self) -> None:
        """When entity is added to Home Assistant."""
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()