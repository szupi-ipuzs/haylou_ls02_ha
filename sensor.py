"""Sensor for Haylou LS02 heart rate statistics."""

import logging
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfMeasurement
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_DEVICE_ADDRESS, CONF_NAME

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

    entity = HaylouHeartRateSensor(
        coordinator, device_address, device_name, config_entry
    )
    async_add_entities([entity])


class HaylouHeartRateSensor(CoordinatorEntity, SensorEntity):
    """Represent Haylou watch heart rate statistics as a sensor."""

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
        self._attr_unique_id = f"{DOMAIN}_{device_address}_heartrate"
        self._attr_name = f"{device_name} Heart Rate"
        self._attr_entity_id = f"sensor.haylou_ls02_heartrate_{device_address.replace(':', '')}"

    @property
    def native_value(self) -> int | None:
        """Return the current heart rate value."""
        hbm_stats = self.coordinator.data.get("hbm_stats")
        if hbm_stats is None:
            return None

        # Return average BPM if available
        if "bpm_avg" in hbm_stats:
            return hbm_stats["bpm_avg"]
        elif "bpm" in hbm_stats:
            return hbm_stats["bpm"]

        return None

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional attributes."""
        hbm_stats = self.coordinator.data.get("hbm_stats")
        battery = self.coordinator.data.get("battery")

        attributes = {}

        if hbm_stats:
            attributes.update(hbm_stats)

        if battery is not None:
            attributes["battery"] = battery

        return attributes

    async def async_added_to_hass(self) -> None:
        """When entity is added to Home Assistant."""
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
