"""Config flow for Haylou LS02 integration."""

import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfo
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import selector

from .const import (
    CONF_DEVICE_ADDRESS,
    CONF_DISTANCE_UNIT,
    CONF_LIFT_WRIST_MODE,
    CONF_PAIRING_PIN,
    CONF_SCREEN_SHOW_TIMEOUT_SECONDS,
    CONF_STEP_GOAL,
    CONF_TIME_FORMAT,
    CONF_USER_AGE,
    CONF_USER_GENDER,
    CONF_USER_HEIGHT_CM,
    CONF_USER_WEIGHT_KG,
    CONF_WEATHER_SOURCE,
    DEFAULT_DISTANCE_UNIT,
    DEFAULT_LIFT_WRIST_MODE,
    DEFAULT_PAIRING_PIN,
    DEFAULT_SCREEN_SHOW_TIMEOUT_SECONDS,
    DEFAULT_STEP_GOAL,
    DEFAULT_TIME_FORMAT,
    DEFAULT_USER_AGE,
    DEFAULT_USER_GENDER,
    DEFAULT_USER_HEIGHT_CM,
    DEFAULT_USER_WEIGHT_KG,
    DEVICE_NAME_FILTER,
    DISTANCE_UNIT_IMPERIAL,
    DISTANCE_UNIT_METRIC,
    DOMAIN,
    LIFT_WRIST_MODE_OFF,
    LIFT_WRIST_MODE_ON,
    TIME_FORMAT_12H,
    TIME_FORMAT_24H,
    USER_GENDER_FEMALE,
    USER_GENDER_MALE,
)

_LOGGER = logging.getLogger(__name__)


def _is_valid_pairing_pin(pin: str) -> bool:
    """Return True if the pairing PIN is exactly four digits."""
    return isinstance(pin, str) and len(pin) == 4 and pin.isdigit()


def _weather_source_schema(default: str | None = None):
    """Return an optional weather source schema entry."""
    if default:
        return vol.Optional(CONF_WEATHER_SOURCE, default=default)
    return vol.Optional(CONF_WEATHER_SOURCE)


class HaylouConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Haylou LS02."""

    VERSION = 1

    def __init__(self):
        """Initialize config flow."""
        self.discovered_devices: Dict[str, BluetoothServiceInfo] = {}
        self.selected_device: Optional[str] = None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return HaylouOptionsFlow()

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle a flow initiated by the user."""
        if user_input is not None:
            if user_input.get("discovery_method") == "scan":
                return await self.async_step_scan()
            else:
                return await self.async_step_manual()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("discovery_method", default="scan"): vol.In(
                        {
                            "scan": "Scan for Haylou Watch",
                            "manual": "Enter device address manually",
                        }
                    ),
                }
            ),
        )

    async def async_step_scan(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Scan for Haylou devices."""
        if user_input is not None:
            if "device" in user_input and not user_input.get("refresh", False):
                # User selected a device from the list
                device_address = user_input["device"]
                self.selected_device = device_address
                return await self.async_step_name()
            elif user_input.get("action") == "manual":
                # User chose to enter address manually
                return await self.async_step_manual()
            # For "retry", "refresh", or any other case, fall through to rescan

        # Get discovered Bluetooth services from Home Assistant
        self.discovered_devices = {}

        # Use the bluetooth module to get discovered services
        try:
            discovered_services = bluetooth.async_discovered_service_info(self.hass)

            for service_info in discovered_services:
                # Check if device advertises as "Haylou Smart Watch 2"
                if (
                    service_info.name == DEVICE_NAME_FILTER
                    and service_info.address
                ):
                    self.discovered_devices[service_info.address] = service_info
        except Exception as e:
            _LOGGER.warning("Error getting Bluetooth devices: %s", e)

        if not self.discovered_devices:
            return self.async_show_form(
                step_id="scan",
                data_schema=vol.Schema(
                    {
                        vol.Required("action", default="retry"): vol.In(
                            {
                                "retry": "Retry scan",
                                "manual": "Enter device address manually",
                            }
                        ),
                    }
                ),
                description_placeholders={
                    "error": "No Haylou Smart Watch 2 devices found. Make sure your watch is powered on and in Bluetooth range.",
                },
            )

        # Create device list for user to choose from
        device_options = {
            addr: f"{DEVICE_NAME_FILTER} ({addr})"
            for addr in self.discovered_devices.keys()
        }

        return self.async_show_form(
            step_id="scan",
            data_schema=vol.Schema(
                {
                    vol.Required("device"): vol.In(device_options),
                    vol.Optional("refresh", default=False): bool,
                }
            ),
        )

    async def async_step_manual(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle manual device address entry."""
        errors = {}

        if user_input is not None:
            device_address = user_input[CONF_DEVICE_ADDRESS].upper()

            # Validate address format
            if not self._is_valid_mac(device_address):
                errors[CONF_DEVICE_ADDRESS] = "invalid_address_format"
            else:
                # Check if already configured
                await self.async_set_unique_id(device_address)
                self._abort_if_unique_id_configured()

                self.selected_device = device_address
                return await self.async_step_name()

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ADDRESS): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "device_name": DEVICE_NAME_FILTER,
            },
        )

    async def async_step_name(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Let user assign a friendly name and weather source to the device."""
        errors = {}

        if user_input is not None:
            device_name = user_input.get(CONF_NAME, "Haylou Watch")
            weather_source = user_input.get(CONF_WEATHER_SOURCE) or None
            pairing_pin = user_input.get(CONF_PAIRING_PIN, DEFAULT_PAIRING_PIN)
            time_format = user_input.get(CONF_TIME_FORMAT, DEFAULT_TIME_FORMAT)
            distance_unit = user_input.get(CONF_DISTANCE_UNIT, DEFAULT_DISTANCE_UNIT)
            user_height_cm = user_input.get(CONF_USER_HEIGHT_CM, DEFAULT_USER_HEIGHT_CM)
            user_weight_kg = user_input.get(CONF_USER_WEIGHT_KG, DEFAULT_USER_WEIGHT_KG)
            user_age = user_input.get(CONF_USER_AGE, DEFAULT_USER_AGE)
            user_gender = user_input.get(CONF_USER_GENDER, DEFAULT_USER_GENDER)
            screen_timeout = user_input.get(
                CONF_SCREEN_SHOW_TIMEOUT_SECONDS,
                DEFAULT_SCREEN_SHOW_TIMEOUT_SECONDS,
            )
            step_goal = user_input.get(CONF_STEP_GOAL, DEFAULT_STEP_GOAL)
            lift_wrist_mode = user_input.get(
                CONF_LIFT_WRIST_MODE,
                DEFAULT_LIFT_WRIST_MODE,
            )

            if not _is_valid_pairing_pin(pairing_pin):
                errors[CONF_PAIRING_PIN] = "invalid_pairing_pin"
            else:
                # Create config entry with weather source saved as options
                return self.async_create_entry(
                    title=device_name,
                    data={
                        CONF_DEVICE_ADDRESS: self.selected_device,
                        CONF_NAME: device_name,
                    },
                    options={
                        CONF_WEATHER_SOURCE: weather_source,
                        CONF_PAIRING_PIN: pairing_pin,
                        CONF_TIME_FORMAT: time_format,
                        CONF_DISTANCE_UNIT: distance_unit,
                        CONF_USER_HEIGHT_CM: user_height_cm,
                        CONF_USER_WEIGHT_KG: user_weight_kg,
                        CONF_USER_AGE: user_age,
                        CONF_USER_GENDER: user_gender,
                        CONF_SCREEN_SHOW_TIMEOUT_SECONDS: screen_timeout,
                        CONF_STEP_GOAL: step_goal,
                        CONF_LIFT_WRIST_MODE: lift_wrist_mode,
                    },
                )

        return self.async_show_form(
            step_id="name",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default="Haylou Watch"): str,
                    _weather_source_schema(): selector({"entity": {"domain": "weather"}}),
                    vol.Optional(
                        CONF_PAIRING_PIN,
                        default=DEFAULT_PAIRING_PIN,
                    ): str,
                    vol.Optional(
                        CONF_TIME_FORMAT,
                        default=DEFAULT_TIME_FORMAT,
                    ): vol.In([TIME_FORMAT_12H, TIME_FORMAT_24H]),
                    vol.Optional(
                        CONF_DISTANCE_UNIT,
                        default=DEFAULT_DISTANCE_UNIT,
                    ): vol.In([DISTANCE_UNIT_METRIC, DISTANCE_UNIT_IMPERIAL]),
                    vol.Optional(
                        CONF_USER_HEIGHT_CM,
                        default=DEFAULT_USER_HEIGHT_CM,
                    ): vol.All(vol.Coerce(int), vol.Range(min=100, max=220)),
                    vol.Optional(
                        CONF_USER_WEIGHT_KG,
                        default=DEFAULT_USER_WEIGHT_KG,
                    ): vol.All(vol.Coerce(int), vol.Range(min=40, max=200)),
                    vol.Optional(
                        CONF_USER_AGE,
                        default=DEFAULT_USER_AGE,
                    ): vol.All(vol.Coerce(int), vol.Range(min=5, max=120)),
                    vol.Optional(
                        CONF_USER_GENDER,
                        default=DEFAULT_USER_GENDER,
                    ): vol.In([USER_GENDER_MALE, USER_GENDER_FEMALE]),
                    vol.Optional(
                        CONF_SCREEN_SHOW_TIMEOUT_SECONDS,
                        default=DEFAULT_SCREEN_SHOW_TIMEOUT_SECONDS,
                    ): vol.All(vol.Coerce(int), vol.Range(min=3, max=30)),
                    vol.Optional(
                        CONF_STEP_GOAL,
                        default=DEFAULT_STEP_GOAL,
                    ): vol.All(vol.Coerce(int), vol.Range(min=100, max=65000)),
                    vol.Optional(
                        CONF_LIFT_WRIST_MODE,
                        default=DEFAULT_LIFT_WRIST_MODE,
                    ): vol.In([LIFT_WRIST_MODE_ON, LIFT_WRIST_MODE_OFF]),
                }
            ),
            errors=errors,
            description_placeholders={"device_address": self.selected_device},
        )

    @staticmethod
    def _is_valid_mac(address: str) -> bool:
        """Validate MAC address format."""
        if not isinstance(address, str):
            return False
        parts = address.split(":")
        return len(parts) == 6 and all(len(part) == 2 for part in parts)

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfo
    ) -> FlowResult:
        """Handle Bluetooth discovery."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        # Check if this is a Haylou watch
        if discovery_info.name != DEVICE_NAME_FILTER:
            return self.async_abort_reason("not_haylou_watch")

        self.discovered_devices[discovery_info.address] = discovery_info
        self.selected_device = discovery_info.address

        return await self.async_step_name()


class HaylouOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Haylou LS02."""

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Manage the options."""
        errors = {}

        if user_input is not None:
            pairing_pin = user_input.get(CONF_PAIRING_PIN, DEFAULT_PAIRING_PIN)
            if _is_valid_pairing_pin(pairing_pin):
                if not user_input.get(CONF_WEATHER_SOURCE):
                    user_input = dict(user_input)
                    user_input.pop(CONF_WEATHER_SOURCE, None)
                return self.async_create_entry(title="", data=user_input)
            errors[CONF_PAIRING_PIN] = "invalid_pairing_pin"

        weather_default = self.config_entry.options.get(
            CONF_WEATHER_SOURCE,
            self.config_entry.data.get(CONF_WEATHER_SOURCE),
        )
        pairing_pin_default = self.config_entry.options.get(
            CONF_PAIRING_PIN,
            DEFAULT_PAIRING_PIN,
        )
        time_format_default = self.config_entry.options.get(
            CONF_TIME_FORMAT,
            DEFAULT_TIME_FORMAT,
        )
        distance_unit_default = self.config_entry.options.get(
            CONF_DISTANCE_UNIT,
            DEFAULT_DISTANCE_UNIT,
        )
        user_height_default = self.config_entry.options.get(
            CONF_USER_HEIGHT_CM,
            DEFAULT_USER_HEIGHT_CM,
        )
        user_weight_default = self.config_entry.options.get(
            CONF_USER_WEIGHT_KG,
            DEFAULT_USER_WEIGHT_KG,
        )
        user_age_default = self.config_entry.options.get(
            CONF_USER_AGE,
            DEFAULT_USER_AGE,
        )
        user_gender_default = self.config_entry.options.get(
            CONF_USER_GENDER,
            DEFAULT_USER_GENDER,
        )
        screen_timeout_default = self.config_entry.options.get(
            CONF_SCREEN_SHOW_TIMEOUT_SECONDS,
            DEFAULT_SCREEN_SHOW_TIMEOUT_SECONDS,
        )
        step_goal_default = self.config_entry.options.get(
            CONF_STEP_GOAL,
            DEFAULT_STEP_GOAL,
        )
        lift_wrist_mode_default = self.config_entry.options.get(
            CONF_LIFT_WRIST_MODE,
            DEFAULT_LIFT_WRIST_MODE,
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    _weather_source_schema(weather_default): selector({"entity": {"domain": "weather"}}),
                    vol.Optional(
                        CONF_PAIRING_PIN,
                        default=pairing_pin_default,
                    ): str,
                    vol.Optional(
                        CONF_TIME_FORMAT,
                        default=time_format_default,
                    ): vol.In([TIME_FORMAT_12H, TIME_FORMAT_24H]),
                    vol.Optional(
                        CONF_DISTANCE_UNIT,
                        default=distance_unit_default,
                    ): vol.In([DISTANCE_UNIT_METRIC, DISTANCE_UNIT_IMPERIAL]),
                    vol.Optional(
                        CONF_USER_HEIGHT_CM,
                        default=user_height_default,
                    ): vol.All(vol.Coerce(int), vol.Range(min=100, max=220)),
                    vol.Optional(
                        CONF_USER_WEIGHT_KG,
                        default=user_weight_default,
                    ): vol.All(vol.Coerce(int), vol.Range(min=40, max=200)),
                    vol.Optional(
                        CONF_USER_AGE,
                        default=user_age_default,
                    ): vol.All(vol.Coerce(int), vol.Range(min=5, max=120)),
                    vol.Optional(
                        CONF_USER_GENDER,
                        default=user_gender_default,
                    ): vol.In([USER_GENDER_MALE, USER_GENDER_FEMALE]),
                    vol.Optional(
                        CONF_SCREEN_SHOW_TIMEOUT_SECONDS,
                        default=screen_timeout_default,
                    ): vol.All(vol.Coerce(int), vol.Range(min=3, max=30)),
                    vol.Optional(
                        CONF_STEP_GOAL,
                        default=step_goal_default,
                    ): vol.All(vol.Coerce(int), vol.Range(min=100, max=65000)),
                    vol.Optional(
                        CONF_LIFT_WRIST_MODE,
                        default=lift_wrist_mode_default,
                    ): vol.In([LIFT_WRIST_MODE_ON, LIFT_WRIST_MODE_OFF]),
                }
            ),
            errors=errors,
        )
