"""Sensor for Haylou LS02 heart rate statistics."""

import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
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
    """Set up sensor for Haylou LS02."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    device_address = config_entry.data[CONF_DEVICE_ADDRESS]
    device_name = config_entry.data.get(CONF_NAME, "Haylou Watch")

    entities = [
        HaylouHeartRateCurrentSensor(
            coordinator, device_address, device_name, config_entry
        ),
        HaylouHeartRateMaxSensor(
            coordinator, device_address, device_name, config_entry
        ),
        HaylouHeartRateMinSensor(
            coordinator, device_address, device_name, config_entry
        ),
        HaylouHeartRateAverageSensor(
            coordinator, device_address, device_name, config_entry
        ),
        HaylouBatteryLevelSensor(
            coordinator, device_address, device_name, config_entry
        ),
        HaylouConnectionStatusSensor(
            coordinator, device_address, device_name, config_entry
        ),
    ]
    async_add_entities(entities)


class HaylouHeartRateCurrentSensor(CoordinatorEntity, SensorEntity):
    """Represent Haylou watch current heart rate as a sensor."""

    _attr_icon = "mdi:heart-pulse"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "bpm"
    _attr_should_poll = False

    def __init__(self, coordinator, device_address: str, device_name: str, config_entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.device_address = device_address
        self.device_name = device_name
        self.config_entry = config_entry
        self._attr_unique_id = f"{DOMAIN}_{device_address}_heartrate_current"
        self._attr_name = f"{device_name} Heart Rate Current"
        self._attr_entity_id = f"sensor.haylou_ls02_heartrate_current_{device_address.replace(':', '')}"

    @property
    def native_value(self) -> int | None:
        """Return the current heart rate value."""
        return self.coordinator.data.get("current_heart_rate")

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


class HaylouHeartRateMaxSensor(CoordinatorEntity, SensorEntity):
    """Represent Haylou watch maximum heart rate as a sensor."""

    _attr_icon = "mdi:heart-pulse"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "bpm"
    _attr_should_poll = False

    def __init__(self, coordinator, device_address: str, device_name: str, config_entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.device_address = device_address
        self.device_name = device_name
        self.config_entry = config_entry
        self._attr_unique_id = f"{DOMAIN}_{device_address}_heartrate_max"
        self._attr_name = f"{device_name} Heart Rate Max"
        self._attr_entity_id = f"sensor.haylou_ls02_heartrate_max_{device_address.replace(':', '')}"

    @property
    def native_value(self) -> int | None:
        """Return the maximum heart rate value."""
        hbm_stats = self.coordinator.data.get("hbm_stats")
        if hbm_stats is None:
            return None

        # Return max BPM
        if "bpm_max" in hbm_stats:
            return hbm_stats["bpm_max"]

        return None

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


class HaylouHeartRateMinSensor(CoordinatorEntity, SensorEntity):
    """Represent Haylou watch minimum heart rate as a sensor."""

    _attr_icon = "mdi:heart-pulse"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "bpm"
    _attr_should_poll = False

    def __init__(self, coordinator, device_address: str, device_name: str, config_entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.device_address = device_address
        self.device_name = device_name
        self.config_entry = config_entry
        self._attr_unique_id = f"{DOMAIN}_{device_address}_heartrate_min"
        self._attr_name = f"{device_name} Heart Rate Min"
        self._attr_entity_id = f"sensor.haylou_ls02_heartrate_min_{device_address.replace(':', '')}"

    @property
    def native_value(self) -> int | None:
        """Return the minimum heart rate value."""
        hbm_stats = self.coordinator.data.get("hbm_stats")
        if hbm_stats is None:
            return None

        # Return min BPM
        if "bpm_min" in hbm_stats:
            return hbm_stats["bpm_min"]

        return None

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


class HaylouHeartRateAverageSensor(CoordinatorEntity, SensorEntity):
    """Represent Haylou watch average heart rate as a sensor."""

    _attr_icon = "mdi:heart-pulse"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "bpm"
    _attr_should_poll = False

    def __init__(self, coordinator, device_address: str, device_name: str, config_entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.device_address = device_address
        self.device_name = device_name
        self.config_entry = config_entry
        self._attr_unique_id = f"{DOMAIN}_{device_address}_heartrate_average"
        self._attr_name = f"{device_name} Heart Rate Average"
        self._attr_entity_id = f"sensor.haylou_ls02_heartrate_average_{device_address.replace(':', '')}"

    @property
    def native_value(self) -> int | None:
        """Return the average heart rate value."""
        hbm_stats = self.coordinator.data.get("hbm_stats")
        if hbm_stats is None:
            return None

        # Return average BPM
        if "bpm_avg" in hbm_stats:
            return hbm_stats["bpm_avg"]

        return None

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


class HaylouBatteryLevelSensor(CoordinatorEntity, SensorEntity):
    """Represent current Haylou watch battery level as a sensor."""

    _attr_icon = "mdi:battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"
    _attr_should_poll = False

    def __init__(self, coordinator, device_address: str, device_name: str, config_entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.device_address = device_address
        self.device_name = device_name
        self.config_entry = config_entry
        self._attr_unique_id = f"{DOMAIN}_{device_address}_battery_level"
        self._attr_name = f"{device_name} Battery Level"
        self._attr_entity_id = f"sensor.haylou_ls02_battery_level_{device_address.replace(':', '')}"

    @property
    def native_value(self) -> int | None:
        """Return the current battery level."""
        return self.coordinator.data.get("battery")

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


class HaylouConnectionStatusSensor(CoordinatorEntity, SensorEntity):
    """Represent Haylou watch BLE connection status as a diagnostic sensor."""

    _attr_icon = "mdi:watch"
    _attr_should_poll = False

    def __init__(self, coordinator, device_address: str, device_name: str, config_entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.device_address = device_address
        self.device_name = device_name
        self.config_entry = config_entry
        self._attr_unique_id = f"{DOMAIN}_{device_address}_connection_status"
        self._attr_name = f"{device_name} Connection Status"
        self._attr_entity_id = f"sensor.haylou_ls02_connection_status_{device_address.replace(':', '')}"

    @property
    def native_value(self) -> str | None:
        """Return the connection status."""
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
