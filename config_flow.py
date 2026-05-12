"""Config flow for Haylou LS02 integration."""

import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    async_get_bluetooth_devices,
    BluetoothServiceInfo,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.device_registry import format_mac

from .const import CONF_DEVICE_ADDRESS, DEVICE_NAME_FILTER, DOMAIN

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
    ) -> config_entries.OptionFlow:
        """Create the options flow."""
        return HaylouOptionsFlow(config_entry)

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
            # User selected a device from the list
            device_address = user_input["device"]
            self.selected_device = device_address
            return await self.async_step_name()

        # Get Bluetooth devices from Home Assistant
        devices = async_get_bluetooth_devices(self.hass)
        self.discovered_devices = {}

        for device in devices.values():
            # Check if device advertises as "Haylou Smart Watch 2"
            if (
                device.name == DEVICE_NAME_FILTER
                and device.address
            ):
                # Check if this device is already configured
                await self.async_set_unique_id(device.address)
                self._abort_if_unique_id_configured()

                self.discovered_devices[device.address] = device

        if not self.discovered_devices:
            return self.async_abort_reason("no_devices_found")

        # Create device list for user to choose from
        device_options = {
            addr: f"{DEVICE_NAME_FILTER} ({addr})"
            for addr in self.discovered_devices.keys()
        }

        return self.async_show_form(
            step_id="scan",
            data_schema=vol.Schema(
                {vol.Required("device"): vol.In(device_options)}
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
        )

    async def async_step_name(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Let user assign a friendly name to the device."""
        if user_input is not None:
            device_name = user_input.get(CONF_NAME, f"Haylou Watch")

            # Create config entry
            return self.async_create_entry(
                title=device_name,
                data={
                    CONF_DEVICE_ADDRESS: self.selected_device,
                    CONF_NAME: device_name,
                },
            )

        return self.async_show_form(
            step_id="name",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default="Haylou Watch"): str,
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


class HaylouOptionsFlow(config_entries.OptionFlow):
    """Handle options for Haylou LS02."""

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "polling_interval",
                        default=self.config_entry.options.get("polling_interval", 60),
                    ): int,
                }
            ),
        )
