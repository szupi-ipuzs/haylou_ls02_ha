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

from .const import CONF_DEVICE_ADDRESS, CONF_WEATHER_SOURCE, DEVICE_NAME_FILTER, DOMAIN

_LOGGER = logging.getLogger(__name__)


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
        if user_input is not None:
            device_name = user_input.get(CONF_NAME, "Haylou Watch")
            weather_source = user_input.get(CONF_WEATHER_SOURCE)

            # Create config entry with weather source saved as options
            return self.async_create_entry(
                title=device_name,
                data={
                    CONF_DEVICE_ADDRESS: self.selected_device,
                    CONF_NAME: device_name,
                },
                options={
                    CONF_WEATHER_SOURCE: weather_source,
                },
            )

        return self.async_show_form(
            step_id="name",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default="Haylou Watch"): str,
                    vol.Optional(
                        CONF_WEATHER_SOURCE,
                        default=None,
                    ): selector({"entity": {"domain": "weather"}}),
                }
            ),
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
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        weather_default = self.config_entry.options.get(
            CONF_WEATHER_SOURCE,
            self.config_entry.data.get(CONF_WEATHER_SOURCE),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_WEATHER_SOURCE,
                        default=weather_default,
                    ): selector({"entity": {"domain": "weather"}}),
                }
            ),
        )
