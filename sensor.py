"""Sensor for Haylou LS02 heart rate statistics."""

import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_NAME,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_WEATHER_SOURCE, DOMAIN, MANUFACTURER, MODEL, CONF_DEVICE_ADDRESS

_LOGGER = logging.getLogger(__name__)

WEATHER_CONDITION_TO_WATCH_TYPE = {
    "clear": 1,
    "sunny": 1,
    "partlycloudy": 2,
    "cloudy": 2,
    "fog": 10,
    "windy": 11,
    "windy-variant": 11,
    "rainy": 5,
    "pouring": 4,
    "lightning": 4,
    "lightning-rainy": 4,
    "snowy": 8,
    "snowy-rainy": 8,
    "hail": 4,
    "clear-night": 12,
    "partlycloudy-night": 13,
    "cloudy-night": 13,
    "exceptional": 9,
}


def _convert_to_celsius(value: Any, unit: str | None = None) -> int | None:
    """Convert a temperature value to Celsius if needed."""
    if value is None:
        return None

    try:
        temperature = float(value)
    except (TypeError, ValueError):
        return None

    if unit is not None:
        unit_value = str(unit).strip().lower()
        if unit_value in {"°f", "f", "fahrenheit"}:
            return int(round((temperature - 32) * 5.0 / 9.0))

    return int(round(temperature))


def _map_condition_to_watch_type(condition: str | None) -> int:
    """Map a HA weather condition to a Haylou weather type."""
    if not condition:
        return 9
    return WEATHER_CONDITION_TO_WATCH_TYPE.get(str(condition).strip().lower(), 9)


def _get_forecast_value(forecast: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first value from forecast matching the requested keys."""
    for key in keys:
        if key in forecast:
            return forecast[key]
    return None


def extract_weather_data(hass: HomeAssistant, entity_id: str) -> dict[str, Any] | None:
    """Extract today and next day weather data from a weather entity."""
    if not entity_id:
        return None

    weather_state = hass.states.get(entity_id)
    if weather_state is None:
        _LOGGER.debug("Weather entity %s not found", entity_id)
        return None

    if weather_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        _LOGGER.debug("Weather entity %s is unavailable or unknown", entity_id)
        return None

    weather_unit = weather_state.attributes.get("temperature_unit") or weather_state.attributes.get("unit_of_measurement")
    current_temperature = _convert_to_celsius(
        weather_state.attributes.get(ATTR_TEMPERATURE), weather_unit
    )

    forecast = weather_state.attributes.get("forecast") or []
    if not isinstance(forecast, list) or len(forecast) < 2:
        _LOGGER.debug("Weather entity %s does not contain enough forecast data", entity_id)
        return None

    today_forecast = forecast[0]
    next_forecast = forecast[1]

    today_max = _convert_to_celsius(
        _get_forecast_value(today_forecast, ("temperature", "temp", "high", "high_temp")),
        weather_unit,
    )
    today_min = _convert_to_celsius(
        _get_forecast_value(today_forecast, ("templow", "temperature_low", "low")),
        weather_unit,
    )
    today_condition = _get_forecast_value(today_forecast, ("condition",)) or weather_state.state
    today_type = _map_condition_to_watch_type(today_condition)

    next_max = _convert_to_celsius(
        _get_forecast_value(next_forecast, ("temperature", "temp", "high", "high_temp")),
        weather_unit,
    )
    next_min = _convert_to_celsius(
        _get_forecast_value(next_forecast, ("templow", "temperature_low", "low")),
        weather_unit,
    )
    next_condition = _get_forecast_value(next_forecast, ("condition",))
    next_type = _map_condition_to_watch_type(next_condition)

    if today_min is None or today_max is None or next_min is None or next_max is None:
        _LOGGER.debug("Weather entity %s has incomplete forecast data", entity_id)
        return None

    if current_temperature is None:
        current_temperature = today_max

    return {
        "entity_id": entity_id,
        "today": {
            "condition": today_condition,
            "weather_type": today_type,
            "current_temperature": current_temperature,
            "min_temperature": today_min,
            "max_temperature": today_max,
        },
        "next": {
            "condition": next_condition,
            "weather_type": next_type,
            "min_temperature": next_min,
            "max_temperature": next_max,
        },
    }


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
        HaylouWeatherSourceSensor(
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


class HaylouWeatherSourceSensor(CoordinatorEntity, SensorEntity):
    """Represent an external weather source selected by the user."""

    _attr_icon = "mdi:weather-partly-cloudy"
    _attr_native_unit_of_measurement = "°C"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_should_poll = False

    def __init__(self, coordinator, device_address: str, device_name: str, config_entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.device_address = device_address
        self.device_name = device_name
        self.config_entry = config_entry
        self._attr_unique_id = f"{DOMAIN}_{device_address}_weather_source"
        self._attr_name = f"{device_name} Weather Source"
        self._attr_entity_id = f"sensor.haylou_ls02_weather_source_{device_address.replace(':', '')}"

    @property
    def native_value(self) -> float | None:
        """Return the current weather temperature from the selected source."""
        weather_data = self._get_external_weather_data()
        return weather_data.get("today", {}).get("current_temperature")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return available weather attributes."""
        weather_data = self._get_external_weather_data()
        attributes: dict[str, Any] = {}
        today = weather_data.get("today") or {}
        next_day = weather_data.get("next") or {}

        if today.get("condition") is not None:
            attributes['condition'] = today["condition"]
        if weather_data.get("entity_id") is not None:
            attributes["weather_source_entity_id"] = weather_data["entity_id"]
        if today.get("min_temperature") is not None:
            attributes["today_min_temperature"] = today["min_temperature"]
        if today.get("max_temperature") is not None:
            attributes["today_max_temperature"] = today["max_temperature"]
        if next_day.get("condition") is not None:
            attributes["tomorrow_condition"] = next_day["condition"]
        if next_day.get("min_temperature") is not None:
            attributes["tomorrow_min_temperature"] = next_day["min_temperature"]
        if next_day.get("max_temperature") is not None:
            attributes["tomorrow_max_temperature"] = next_day["max_temperature"]

        return attributes

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information for the Haylou watch."""
        return {
            "identifiers": {(DOMAIN, self.device_address)},
            "name": self.device_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
        }

    def _get_external_weather_data(self) -> dict[str, Any]:
        """Read weather data from the selected weather entity."""
        entity_id = self.config_entry.options.get(CONF_WEATHER_SOURCE)
        weather_data = extract_weather_data(self.hass, entity_id)
        if weather_data is None:
            return {"today": {}, "next": {}, "entity_id": entity_id}
        return weather_data

    async def async_added_to_hass(self) -> None:
        """When entity is added to Home Assistant."""
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
