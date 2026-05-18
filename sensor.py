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
from homeassistant.helpers.entity import EntityCategory
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


def _get_weather_unit(weather_state) -> str | None:
    """Return the temperature unit configured on a weather entity state."""
    return weather_state.attributes.get("temperature_unit") or weather_state.attributes.get(
        "unit_of_measurement"
    )


NEXT_FORECAST_DAYS = 3


def _parse_forecast_day(
    forecast_entry: dict[str, Any],
    weather_unit: str | None,
    fallback_condition: str | None = None,
) -> dict[str, Any] | None:
    """Parse a single daily forecast entry for the watch protocol."""
    max_temperature = _convert_to_celsius(
        _get_forecast_value(
            forecast_entry,
            ("temperature", "temp", "high", "high_temp", "native_temperature"),
        ),
        weather_unit,
    )
    min_temperature = _convert_to_celsius(
        _get_forecast_value(
            forecast_entry,
            ("templow", "temperature_low", "low", "native_templow"),
        ),
        weather_unit,
    )
    if max_temperature is None or min_temperature is None:
        return None

    condition = _get_forecast_value(forecast_entry, ("condition",)) or fallback_condition
    return {
        "condition": condition,
        "weather_type": _map_condition_to_watch_type(condition),
        "min_temperature": min_temperature,
        "max_temperature": max_temperature,
    }


def _build_next_forecast_days(
    forecast: list[dict[str, Any]], weather_unit: str | None
) -> list[dict[str, Any]] | None:
    """Build the next three daily forecast entries for set_weather_next."""
    future_forecast = forecast[1:]
    if not future_forecast:
        return None

    next_days: list[dict[str, Any]] = []
    for index in range(NEXT_FORECAST_DAYS):
        forecast_entry = (
            future_forecast[index]
            if index < len(future_forecast)
            else future_forecast[-1]
        )
        day = _parse_forecast_day(forecast_entry, weather_unit)
        if day is None:
            return None
        next_days.append(day)

    return next_days


def _build_weather_data(entity_id: str, weather_state, forecast: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Build watch weather payload from entity state and forecast entries."""
    if not forecast:
        return None

    weather_unit = _get_weather_unit(weather_state)
    today = _parse_forecast_day(forecast[0], weather_unit, weather_state.state)
    if today is None:
        _LOGGER.debug("Weather entity %s has incomplete forecast data for today", entity_id)
        return None

    next_days = _build_next_forecast_days(forecast, weather_unit)
    if next_days is None:
        _LOGGER.debug("Weather entity %s has incomplete forecast data for next days", entity_id)
        return None

    current_temperature = _convert_to_celsius(
        weather_state.attributes.get(ATTR_TEMPERATURE), weather_unit
    )
    if current_temperature is None:
        current_temperature = today["max_temperature"]

    return {
        "entity_id": entity_id,
        "today": {
            **today,
            "current_temperature": current_temperature,
        },
        "next": next_days[0],
        "next_days": next_days,
    }


async def async_fetch_weather_forecast(hass: HomeAssistant, entity_id: str) -> list[dict[str, Any]] | None:
    """Fetch daily forecast entries for a weather entity."""
    weather_state = hass.states.get(entity_id)
    if weather_state is None:
        return None

    legacy_forecast = weather_state.attributes.get("forecast")
    if isinstance(legacy_forecast, list) and legacy_forecast:
        return legacy_forecast

    try:
        from homeassistant.components.weather import (
            DATA_COMPONENT,
            WeatherEntity,
            WeatherEntityFeature,
        )
        from homeassistant.helpers.entity_component import EntityComponent
    except ImportError:
        return None

    component: EntityComponent[WeatherEntity] | None = hass.data.get(DATA_COMPONENT)
    if component is None:
        return None

    entity = component.get_entity(entity_id)
    if entity is None:
        return None

    supported_features = entity.supported_features or 0
    native_forecast = None

    if supported_features & WeatherEntityFeature.FORECAST_DAILY:
        native_forecast = await entity.async_forecast_daily()
    elif supported_features & WeatherEntityFeature.FORECAST_TWICE_DAILY:
        native_forecast = await entity.async_forecast_twice_daily()
    elif supported_features & WeatherEntityFeature.FORECAST_HOURLY:
        native_forecast = await entity.async_forecast_hourly()

    if not native_forecast:
        return None

    converted = entity._convert_forecast(native_forecast)  # noqa: SLF001
    if not isinstance(converted, list):
        return None
    return converted


async def async_extract_weather_data(hass: HomeAssistant, entity_id: str) -> dict[str, Any] | None:
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

    forecast = await async_fetch_weather_forecast(hass, entity_id)
    if not isinstance(forecast, list) or not forecast:
        _LOGGER.debug("Weather entity %s does not contain forecast data", entity_id)
        return None

    return _build_weather_data(entity_id, weather_state, forecast)


def extract_weather_data(hass: HomeAssistant, entity_id: str) -> dict[str, Any] | None:
    """Extract weather data using the legacy forecast state attribute."""
    if not entity_id:
        return None

    weather_state = hass.states.get(entity_id)
    if weather_state is None:
        _LOGGER.debug("Weather entity %s not found", entity_id)
        return None

    if weather_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        _LOGGER.debug("Weather entity %s is unavailable or unknown", entity_id)
        return None

    forecast = weather_state.attributes.get("forecast") or []
    if not isinstance(forecast, list) or not forecast:
        return None

    return _build_weather_data(entity_id, weather_state, forecast)


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
        HaylouStepsSensor(
            coordinator, device_address, device_name, config_entry
        ),
    ]
    async_add_entities(entities)


class HaylouSensorEntity(CoordinatorEntity, SensorEntity):
    """Base class for Haylou watch sensors."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator,
        device_address: str,
        device_name: str,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.device_address = device_address
        self.device_name = device_name
        self.config_entry = config_entry

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


class HaylouHeartRateCurrentSensor(HaylouSensorEntity):
    """Represent Haylou watch current heart rate as a sensor."""

    _attr_icon = "mdi:heart-pulse"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "bpm"

    def __init__(self, coordinator, device_address: str, device_name: str, config_entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator, device_address, device_name, config_entry)
        self._attr_unique_id = f"{DOMAIN}_{device_address}_heartrate_current"
        self._attr_name = "Heart Rate Current"

    @property
    def native_value(self) -> int | None:
        """Return the current heart rate value."""
        return self.coordinator.data.get("current_heart_rate")


class HaylouHeartRateMaxSensor(HaylouSensorEntity):
    """Represent Haylou watch maximum heart rate as a sensor."""

    _attr_icon = "mdi:heart-pulse"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "bpm"

    def __init__(self, coordinator, device_address: str, device_name: str, config_entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator, device_address, device_name, config_entry)
        self._attr_unique_id = f"{DOMAIN}_{device_address}_heartrate_max"
        self._attr_name = "Heart Rate Max"

    @property
    def native_value(self) -> int | None:
        """Return the maximum heart rate value."""
        hbm_stats = self.coordinator.data.get("hbm_stats")
        if hbm_stats is None:
            return None

        if "bpm_max" in hbm_stats:
            return hbm_stats["bpm_max"]

        return None


class HaylouHeartRateMinSensor(HaylouSensorEntity):
    """Represent Haylou watch minimum heart rate as a sensor."""

    _attr_icon = "mdi:heart-pulse"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "bpm"

    def __init__(self, coordinator, device_address: str, device_name: str, config_entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator, device_address, device_name, config_entry)
        self._attr_unique_id = f"{DOMAIN}_{device_address}_heartrate_min"
        self._attr_name = "Heart Rate Min"

    @property
    def native_value(self) -> int | None:
        """Return the minimum heart rate value."""
        hbm_stats = self.coordinator.data.get("hbm_stats")
        if hbm_stats is None:
            return None

        if "bpm_min" in hbm_stats:
            return hbm_stats["bpm_min"]

        return None


class HaylouHeartRateAverageSensor(HaylouSensorEntity):
    """Represent Haylou watch average heart rate as a sensor."""

    _attr_icon = "mdi:heart-pulse"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "bpm"

    def __init__(self, coordinator, device_address: str, device_name: str, config_entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator, device_address, device_name, config_entry)
        self._attr_unique_id = f"{DOMAIN}_{device_address}_heartrate_average"
        self._attr_name = "Heart Rate Average"

    @property
    def native_value(self) -> int | None:
        """Return the average heart rate value."""
        hbm_stats = self.coordinator.data.get("hbm_stats")
        if hbm_stats is None:
            return None

        if "bpm_avg" in hbm_stats:
            return hbm_stats["bpm_avg"]

        return None


class HaylouStepsSensor(HaylouSensorEntity):
    """Represent Haylou watch steps count as a sensor."""

    _attr_icon = "mdi:shoe-print"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "steps"

    def __init__(self, coordinator, device_address: str, device_name: str, config_entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator, device_address, device_name, config_entry)
        self._attr_unique_id = f"{DOMAIN}_{device_address}_steps"
        self._attr_name = "Steps"

    @property
    def native_value(self) -> int | None:
        """Return the steps count."""
        sport_stats = self.coordinator.data.get("sport_stats")
        if sport_stats is None:
            return None

        if "steps_count" in sport_stats:
            return sport_stats["steps_count"]

        return None


class HaylouBatteryLevelSensor(HaylouSensorEntity):
    """Represent current Haylou watch battery level as a sensor."""

    _attr_icon = "mdi:battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"

    def __init__(self, coordinator, device_address: str, device_name: str, config_entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator, device_address, device_name, config_entry)
        self._attr_unique_id = f"{DOMAIN}_{device_address}_battery_level"
        self._attr_name = "Battery Level"

    @property
    def native_value(self) -> int | None:
        """Return the current battery level."""
        return self.coordinator.data.get("battery")


class HaylouConnectionStatusSensor(HaylouSensorEntity):
    """Represent Haylou watch BLE connection status as a diagnostic sensor."""

    _attr_icon = "mdi:watch"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_address: str, device_name: str, config_entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator, device_address, device_name, config_entry)
        self._attr_unique_id = f"{DOMAIN}_{device_address}_connection_status"
        self._attr_name = "Connection Status"

    @property
    def native_value(self) -> str | None:
        """Return the connection status."""
        return self.coordinator.data.get("connection_state", "disconnected")


class HaylouWeatherSourceSensor(HaylouSensorEntity):
    """Represent an external weather source selected by the user."""

    _attr_icon = "mdi:weather-partly-cloudy"
    _attr_native_unit_of_measurement = "°C"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_address: str, device_name: str, config_entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator, device_address, device_name, config_entry)
        self._weather_cache: dict[str, Any] | None = None
        self._attr_unique_id = f"{DOMAIN}_{device_address}_weather_source"
        self._attr_name = "Weather Source"

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

    def _get_external_weather_data(self) -> dict[str, Any]:
        """Read weather data from the selected weather entity."""
        entity_id = self.config_entry.options.get(
            CONF_WEATHER_SOURCE,
            self.config_entry.data.get(CONF_WEATHER_SOURCE),
        )
        if self._weather_cache is not None:
            return self._weather_cache
        cached = getattr(self.coordinator, "_cached_weather", None)
        if cached is not None:
            return cached
        weather_data = extract_weather_data(self.hass, entity_id)
        if weather_data is None:
            return {"today": {}, "next": {}, "entity_id": entity_id}
        return weather_data

    async def _async_refresh_weather_cache(self) -> None:
        """Refresh cached weather data from the configured source entity."""
        entity_id = self.config_entry.options.get(
            CONF_WEATHER_SOURCE,
            self.config_entry.data.get(CONF_WEATHER_SOURCE),
        )
        if not entity_id:
            return
        weather_data = await async_extract_weather_data(self.hass, entity_id)
        if weather_data is not None:
            self._weather_cache = weather_data
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """When entity is added to Home Assistant."""
        await super().async_added_to_hass()
        entity_id = self.config_entry.options.get(
            CONF_WEATHER_SOURCE,
            self.config_entry.data.get(CONF_WEATHER_SOURCE),
        )
        if entity_id:
            from homeassistant.helpers.event import async_track_state_change_event

            @callback
            def _weather_source_changed(event) -> None:
                self.hass.async_create_task(self._async_refresh_weather_cache())

            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [entity_id], _weather_source_changed
                )
            )
            await self._async_refresh_weather_cache()
        self._handle_coordinator_update()
