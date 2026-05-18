"""Device tracker for Haylou LS02 watch connection state."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.device_tracker import TrackerEntity, SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    BLE_PRESENCE_TIMEOUT_MINUTES,
    CONF_DEVICE_ADDRESS,
    DOMAIN,
    MANUFACTURER,
    MODEL,
    TRACKER_STATE_AWAY,
    TRACKER_STATE_HOME,
)

_LOGGER = logging.getLogger(__name__)

_PRESENCE_TIMEOUT = timedelta(minutes=BLE_PRESENCE_TIMEOUT_MINUTES)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up device tracker for Haylou LS02."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    device_address = config_entry.data[CONF_DEVICE_ADDRESS]
    device_name = config_entry.data.get(CONF_NAME, "Haylou Watch")

    _LOGGER.debug(
        "Setting up device tracker for %s with MAC %s",
        device_name,
        device_address,
    )
    entity = HaylouDeviceTracker(
        coordinator, device_address, device_name, config_entry
    )
    async_add_entities([entity], update_before_add=True)


class HaylouDeviceTracker(CoordinatorEntity, TrackerEntity):
    """Represent a Haylou watch as a device tracker."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:watch"
    _attr_source_type = SourceType.BLUETOOTH
    _attr_name = "Tracker"

    def __init__(self, coordinator, device_address: str, device_name: str, config_entry: ConfigEntry):
        """Initialize the device tracker."""
        super().__init__(coordinator)
        self.device_address = device_address
        self.device_name = device_name
        self.config_entry = config_entry
        self._attr_unique_id = f"{DOMAIN}_{device_address}_tracker"
        _LOGGER.debug("Initialized HaylouDeviceTracker for %s", device_address)

    @property
    def location_name(self) -> str:
        """Return Home when connected or recently seen, otherwise Away."""
        return TRACKER_STATE_HOME if self._is_home else TRACKER_STATE_AWAY

    @property
    def _is_home(self) -> bool:
        """Return True when the watch is connected or recently detected by BLE."""
        if not self.coordinator or not self.coordinator.data:
            return False

        if self.coordinator.data.get("connection_state") == "connected":
            return True

        return self._was_recently_detected()

    def _was_recently_detected(self) -> bool:
        """Return True if the watch was seen in BLE during the presence window."""
        last_detected = self.coordinator.data.get("last_ble_detected")
        if last_detected is None:
            return False

        if isinstance(last_detected, str):
            try:
                last_detected = datetime.fromisoformat(last_detected)
            except (ValueError, TypeError):
                return False

        if not isinstance(last_detected, datetime):
            return False

        if last_detected.tzinfo is None:
            last_detected = last_detected.replace(tzinfo=timezone.utc)

        return datetime.now(timezone.utc) - last_detected < _PRESENCE_TIMEOUT

    async def async_added_to_hass(self) -> None:
        """When entity is added to Home Assistant."""
        await super().async_added_to_hass()
        _LOGGER.debug("Device tracker %s added to Home Assistant", self.device_address)
        self._handle_coordinator_update()

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information for the Haylou watch."""
        return {
            "identifiers": {(DOMAIN, self.device_address)},
            "connections": {(CONNECTION_BLUETOOTH, self.device_address)},
            "name": self.device_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
