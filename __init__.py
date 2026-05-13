"""The Haylou LS02 integration."""

import asyncio
import logging
import os
from typing import Final

from homeassistant.components.bluetooth import BluetoothServiceInfo, async_last_service_info
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    CONF_DEVICE_ADDRESS,
    DOMAIN,
    ICON_URL,
    SERVICE_SEND_MESSAGE,
    SERVICE_REQUEST_BATTERY,
    SERVICE_REQUEST_HBM_STATUS,
)
from .ble_client import HaylouBLEClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["device_tracker", "sensor"]

SCAN_INTERVAL_SECONDS = 60


class HaylouUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator for Haylou LS02 watch data."""

    def __init__(self, hass: HomeAssistant, ble_client: HaylouBLEClient):
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,  # No automatic polling; reactive updates
        )
        self.ble_client = ble_client
        self.data = {
            "connected": False,
            "current_heart_rate": None,
            "hbm_stats": None,
            "battery": None,
        }

    async def async_config_entry_first_refresh(self) -> bool:
        """First refresh when config entry is set up."""
        try:
            # Connect to device
            if not await self.ble_client.connect():
                raise UpdateFailed("Failed to connect to Haylou watch")

            # Subscribe to notifications
            if not await self.ble_client.subscribe_notifications(self._on_notification):
                raise UpdateFailed("Failed to subscribe to watch notifications")

            # Initialize the watch once connected
            if not await self.ble_client.initialize_watch():
                raise UpdateFailed("Failed to initialize Haylou watch")

            self.data["connected"] = True
            self.last_update_success = True
            return True
        except UpdateFailed as e:
            _LOGGER.error("Update failed: %s", e)
            self.last_update_success = False
            raise

    def _on_notification(self, payload: bytes) -> None:
        """Handle incoming notification from watch."""
        _LOGGER.debug("Received notification: %s", payload.hex())

        # Parse battery status
        battery = self.ble_client.parse_battery_status(payload)
        if battery is not None:
            self.data["battery"] = battery
            self.async_set_updated_data(self.data)
            return

        # Parse current HBM status
        current_hr = self.ble_client.parse_hbm_status(payload)
        if current_hr is not None:
            self.data["current_heart_rate"] = current_hr
            self.async_set_updated_data(self.data)
            return

        # Parse HBM statistics
        hbm_stats = self.ble_client.parse_hbm_statistics(payload)
        if hbm_stats is not None:
            self.data["hbm_stats"] = hbm_stats
            self.async_set_updated_data(self.data)
            return

    async def async_shutdown(self) -> None:
        """Shutdown coordinator and disconnect."""
        await self.ble_client.disconnect()
        self.data["connected"] = False


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up config entry."""
    _LOGGER.debug("Setting up entry for device: %s", entry.data[CONF_DEVICE_ADDRESS])

    # Initialize coordinator
    ble_client = HaylouBLEClient(hass, entry.data[CONF_DEVICE_ADDRESS])
    coordinator = HaylouUpdateCoordinator(hass, ble_client)

    # Perform first refresh
    try:
        await coordinator.async_config_entry_first_refresh()
    except UpdateFailed as e:
        raise ConfigEntryNotReady(f"Failed to connect to Haylou watch: {e}") from e

    # Store coordinator and client in hass.data
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "ble_client": ble_client,
    }

    _register_icon_static_path(hass)

    # Set up entities
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    async_setup_services(hass, entry, coordinator, ble_client)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading entry for device: %s", entry.data[CONF_DEVICE_ADDRESS])

    if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
        coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
        await coordinator.async_shutdown()

        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        if unload_ok:
            hass.data[DOMAIN].pop(entry.entry_id)
            if not hass.data[DOMAIN]:
                hass.data.pop(DOMAIN)
        return unload_ok

    return False


def _register_icon_static_path(hass: HomeAssistant) -> None:
    """Register the integration icon for entity presentation."""
    icon_file_path = os.path.join(os.path.dirname(__file__), "icon.png")
    try:
        if hasattr(hass, "http") and hasattr(hass.http, "register_static_path"):
            hass.http.register_static_path(ICON_URL, icon_file_path, False)
    except Exception as err:
        _LOGGER.debug("Unable to register icon static path: %s", err)


def async_setup_services(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: HaylouUpdateCoordinator,
    ble_client: HaylouBLEClient,
) -> None:
    """Set up integration services."""

    device_address = entry.data[CONF_DEVICE_ADDRESS]
    device_name = entry.data.get(CONF_NAME, "Haylou Watch")

    async def send_message_handler(call):
        """Handle send_message service call."""
        message = call.data.get("message", "")
        msg_type = call.data.get("message_type", "generic")

        _LOGGER.debug("Sending message to %s: %s", device_address, message)

        success = await ble_client.send_message(message, msg_type)
        if not success:
            _LOGGER.error("Failed to send message to %s", device_address)

    async def request_battery_handler(call):
        """Handle request_battery service call."""
        _LOGGER.debug("Requesting battery status from %s", device_address)
        await ble_client.request_battery()

    async def request_hbm_status_handler(call):
        """Handle request_hbm_status service call."""
        _LOGGER.debug("Requesting HBM status from %s", device_address)
        await ble_client.request_hbm_status()

    # Register service for this specific device
    service_send_id = f"{DOMAIN}_{device_address.replace(':', '_')}_send_message"
    service_battery_id = f"{DOMAIN}_{device_address.replace(':', '_')}_request_battery"
    service_hbm_id = f"{DOMAIN}_{device_address.replace(':', '_')}_request_hbm_status"

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_MESSAGE,
        send_message_handler,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REQUEST_BATTERY,
        request_battery_handler,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REQUEST_HBM_STATUS,
        request_hbm_status_handler,
    )

    _LOGGER.debug("Services registered for %s", device_name)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Migrate an old config entry."""
    _LOGGER.debug("Migrating config entry from version %s", config_entry.version)

    if config_entry.version == 1:
        # Current version, no migration needed
        return True

    return False
