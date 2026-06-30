"""Number entities for Haylou LS02 watch user settings."""

from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DEVICE_ADDRESS,
    CONF_SCREEN_SHOW_TIMEOUT_SECONDS,
    CONF_STEP_GOAL,
    CONF_USER_AGE,
    CONF_USER_HEIGHT_CM,
    CONF_USER_WEIGHT_KG,
    DEFAULT_SCREEN_SHOW_TIMEOUT_SECONDS,
    DEFAULT_STEP_GOAL,
    DEFAULT_USER_AGE,
    DEFAULT_USER_HEIGHT_CM,
    DEFAULT_USER_WEIGHT_KG,
    DOMAIN,
    MANUFACTURER,
    MODEL,
)


@dataclass(frozen=True)
class HaylouNumberDescription:
    """Describe a numeric watch setting."""

    key: str
    name: str
    minimum: int
    maximum: int
    default: int


NUMBER_DESCRIPTIONS = (
    HaylouNumberDescription(
        key=CONF_USER_HEIGHT_CM,
        name="User Height",
        minimum=100,
        maximum=220,
        default=DEFAULT_USER_HEIGHT_CM,
    ),
    HaylouNumberDescription(
        key=CONF_USER_WEIGHT_KG,
        name="User Weight",
        minimum=40,
        maximum=200,
        default=DEFAULT_USER_WEIGHT_KG,
    ),
    HaylouNumberDescription(
        key=CONF_USER_AGE,
        name="User Age",
        minimum=5,
        maximum=120,
        default=DEFAULT_USER_AGE,
    ),
    HaylouNumberDescription(
        key=CONF_SCREEN_SHOW_TIMEOUT_SECONDS,
        name="Screen Time",
        minimum=3,
        maximum=30,
        default=DEFAULT_SCREEN_SHOW_TIMEOUT_SECONDS,
    ),
    HaylouNumberDescription(
        key=CONF_STEP_GOAL,
        name="Daily Steps Goal",
        minimum=100,
        maximum=65000,
        default=DEFAULT_STEP_GOAL,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities for Haylou LS02."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    device_address = config_entry.data[CONF_DEVICE_ADDRESS]
    device_name = config_entry.data.get(CONF_NAME, "Haylou Watch")

    async_add_entities(
        [
            HaylouUserInfoNumber(
                coordinator,
                device_address,
                device_name,
                config_entry,
                description,
            )
            for description in NUMBER_DESCRIPTIONS
        ]
    )


class HaylouUserInfoNumber(CoordinatorEntity, NumberEntity):
    """Represent a numeric user info setting."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1

    def __init__(
        self,
        coordinator,
        device_address: str,
        device_name: str,
        config_entry: ConfigEntry,
        description: HaylouNumberDescription,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.device_address = device_address
        self.device_name = device_name
        self.config_entry = config_entry
        self.description = description
        self._attr_unique_id = f"{DOMAIN}_{device_address}_{description.key}"
        self._attr_name = description.name
        self._attr_native_min_value = description.minimum
        self._attr_native_max_value = description.maximum

    @property
    def native_value(self) -> int:
        """Return the current numeric setting value."""
        return int(
            self.config_entry.options.get(
                self.description.key,
                self.description.default,
            )
        )

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

    async def async_set_native_value(self, value: float) -> None:
        """Persist the numeric setting and push user info to the watch."""
        int_value = int(value)
        int_value = max(self.description.minimum, min(self.description.maximum, int_value))
        options = dict(self.config_entry.options)
        options[self.description.key] = int_value
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            options=options,
        )
        self.async_write_ha_state()
