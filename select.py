"""Select entities for Haylou LS02 watch settings."""

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DEVICE_ADDRESS,
    CONF_DISTANCE_UNIT,
    CONF_LIFT_WRIST_MODE,
    CONF_TIME_FORMAT,
    CONF_USER_GENDER,
    DEFAULT_DISTANCE_UNIT,
    DEFAULT_LIFT_WRIST_MODE,
    DEFAULT_TIME_FORMAT,
    DEFAULT_USER_GENDER,
    DISTANCE_UNIT_IMPERIAL,
    DISTANCE_UNIT_METRIC,
    DOMAIN,
    LIFT_WRIST_MODE_OFF,
    LIFT_WRIST_MODE_ON,
    MANUFACTURER,
    MODEL,
    TIME_FORMAT_12H,
    TIME_FORMAT_24H,
    USER_GENDER_FEMALE,
    USER_GENDER_MALE,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up select entities for Haylou LS02."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    device_address = config_entry.data[CONF_DEVICE_ADDRESS]
    device_name = config_entry.data.get(CONF_NAME, "Haylou Watch")

    async_add_entities(
        [
            HaylouTimeFormatSelect(
                coordinator, device_address, device_name, config_entry
            ),
            HaylouDistanceUnitSelect(
                coordinator, device_address, device_name, config_entry
            ),
            HaylouUserGenderSelect(
                coordinator, device_address, device_name, config_entry
            ),
            HaylouLiftWristModeSelect(
                coordinator, device_address, device_name, config_entry
            ),
        ]
    )


class HaylouSelectEntity(CoordinatorEntity, SelectEntity):
    """Base class for Haylou watch select entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        device_address: str,
        device_name: str,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the select entity."""
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
            "sw_version": self.coordinator.data.get("firmware"),
        }

    async def _async_select_option(self, option: str) -> None:
        """Persist a selected option.

        The config entry update listener applies the combined unit settings.
        """
        if option not in self.options:
            raise ValueError(f"Invalid option: {option}")

        options = dict(self.config_entry.options)
        options[self._option_key] = option
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            options=options,
        )
        self.async_write_ha_state()


class HaylouTimeFormatSelect(HaylouSelectEntity):
    """Select the time format displayed on the watch."""

    _attr_name = "Displayed Time Format"
    _attr_options = [TIME_FORMAT_12H, TIME_FORMAT_24H]

    def __init__(
        self,
        coordinator,
        device_address: str,
        device_name: str,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the time format select."""
        super().__init__(coordinator, device_address, device_name, config_entry)
        self._option_key = CONF_TIME_FORMAT
        self._attr_unique_id = f"{DOMAIN}_{device_address}_time_format"

    @property
    def current_option(self) -> str:
        """Return the selected time format."""
        return self.config_entry.options.get(CONF_TIME_FORMAT, DEFAULT_TIME_FORMAT)

    async def async_select_option(self, option: str) -> None:
        """Change the selected time format."""
        await self._async_select_option(option)


class HaylouDistanceUnitSelect(HaylouSelectEntity):
    """Select the distance unit displayed on the watch."""

    _attr_name = "Distance Unit"
    _attr_options = [DISTANCE_UNIT_METRIC, DISTANCE_UNIT_IMPERIAL]

    def __init__(
        self,
        coordinator,
        device_address: str,
        device_name: str,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the distance unit select."""
        super().__init__(coordinator, device_address, device_name, config_entry)
        self._option_key = CONF_DISTANCE_UNIT
        self._attr_unique_id = f"{DOMAIN}_{device_address}_distance_unit"

    @property
    def current_option(self) -> str:
        """Return the selected distance unit."""
        return self.config_entry.options.get(
            CONF_DISTANCE_UNIT,
            DEFAULT_DISTANCE_UNIT,
        )

    async def async_select_option(self, option: str) -> None:
        """Change the selected distance unit."""
        await self._async_select_option(option)


class HaylouUserGenderSelect(HaylouSelectEntity):
    """Select the user gender sent to the watch."""

    _attr_name = "User Gender"
    _attr_options = [USER_GENDER_MALE, USER_GENDER_FEMALE]

    def __init__(
        self,
        coordinator,
        device_address: str,
        device_name: str,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the user gender select."""
        super().__init__(coordinator, device_address, device_name, config_entry)
        self._option_key = CONF_USER_GENDER
        self._attr_unique_id = f"{DOMAIN}_{device_address}_user_gender"

    @property
    def current_option(self) -> str:
        """Return the selected user gender."""
        return self.config_entry.options.get(CONF_USER_GENDER, DEFAULT_USER_GENDER)

    async def async_select_option(self, option: str) -> None:
        """Change the selected user gender."""
        await self._async_select_option(option)


class HaylouLiftWristModeSelect(HaylouSelectEntity):
    """Select whether lift wrist mode is enabled."""

    _attr_name = "Lift Wrist Mode"
    _attr_options = [LIFT_WRIST_MODE_ON, LIFT_WRIST_MODE_OFF]

    def __init__(
        self,
        coordinator,
        device_address: str,
        device_name: str,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the lift wrist mode select."""
        super().__init__(coordinator, device_address, device_name, config_entry)
        self._option_key = CONF_LIFT_WRIST_MODE
        self._attr_unique_id = f"{DOMAIN}_{device_address}_lift_wrist_mode"

    @property
    def current_option(self) -> str:
        """Return the selected lift wrist mode."""
        return self.config_entry.options.get(
            CONF_LIFT_WRIST_MODE,
            DEFAULT_LIFT_WRIST_MODE,
        )

    async def async_select_option(self, option: str) -> None:
        """Change the selected lift wrist mode."""
        await self._async_select_option(option)
