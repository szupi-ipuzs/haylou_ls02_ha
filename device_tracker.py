"""Device tracker for Haylou LS02 watch connection state."""

import logging
from typing import Any
from datetime import datetime, timezone, timedelta

from homeassistant.components.device_tracker import TrackerEntity, SourceType
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

    _attr_icon = "mdi:watch"
    _attr_source_type = SourceType.BLUETOOTH
    _attr_should_poll = False

    def __init__(self, coordinator, device_address: str, device_name: str, config_entry: ConfigEntry):
        """Initialize the device tracker.

        Args:
            coordinator: Data update coordinator
            device_address: MAC address of the Haylou watch (e.g., "AA:BB:CC:DD:EE:FF")
            device_name: User-friendly name for the watch
            config_entry: Configuration entry
        """
        super().__init__(coordinator)
        self.device_address = device_address  # MAC address of the watch
        self.device_name = device_name
        self.config_entry = config_entry
        self._attr_unique_id = f"{DOMAIN}_{device_address}_tracker"
        self._attr_name = f"{device_name} Tracker"
        _LOGGER.debug("Initialized HaylouDeviceTracker for %s", device_address)

    @property
    def latitude(self) -> float | None:
        """Return latitude - not available for BLE tracker."""
        return None

    @property
    def longitude(self) -> float | None:
        """Return longitude - not available for BLE tracker."""
        return None

    @property
    def location_name(self) -> str | None:
        """Return location name (home or away).

        Used instead of coordinates for BLE-based tracking.
        """
        return "home" if self.is_connected else "away"

    @property
    def is_connected(self) -> bool:
        """Return True if the device is home (detected or connected).

        Device is considered home if:
        - Connection state is 'connected' (via BLE connection to MAC address), OR
        - MAC address was detected via BLE within the last 10 minutes

        Returns False (away) if not detected for 10+ minutes.

        Note: Detection uses MAC address only, BLE name is not used.
        """
        if not self.coordinator:
            _LOGGER.debug("Coordinator is None for device %s", self.device_address)
            return False

        if not self.coordinator.data:
            _LOGGER.debug("Coordinator data is None for device %s", self.device_address)
            return False

        try:
            # If actively connected to this MAC address, device is home
            connection_state = self.coordinator.data.get("connection_state", "disconnected")
            _LOGGER.debug("Device %s connection_state: %s", self.device_address, connection_state)

            if connection_state == "connected":
                _LOGGER.debug("Device %s is connected", self.device_address)
                return True

            # Check if this MAC address was detected in BLE scan recently (within 10 minutes)
            last_detected = self.coordinator.data.get("last_ble_detected")
            if last_detected is None:
                _LOGGER.debug("No last_ble_detected for device %s", self.device_address)
                return False

            # Parse timestamp if it's a string
            if isinstance(last_detected, str):
                try:
                    last_detected = datetime.fromisoformat(last_detected)
                except (ValueError, TypeError) as e:
                    _LOGGER.debug("Failed to parse timestamp for %s: %s", self.device_address, e)
                    return False

            # Check if last detection was within 10 minutes
            if isinstance(last_detected, datetime):
                time_since_detection = datetime.now(timezone.utc) - last_detected
                is_home = time_since_detection < timedelta(minutes=10)
                _LOGGER.debug(
                    "Device %s detected %s ago, is_home=%s",
                    self.device_address,
                    time_since_detection,
                    is_home,
                )
                return is_home

            _LOGGER.debug("Unexpected type for last_detected: %s", type(last_detected))
            return False

        except Exception as e:
            _LOGGER.error(
                "Error in is_connected property for %s: %s",
                self.device_address,
                e,
                exc_info=True,
            )
            return False

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
            "name": self.device_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        _LOGGER.debug("Coordinator update for device %s", self.device_address)
        self.async_write_ha_state()
