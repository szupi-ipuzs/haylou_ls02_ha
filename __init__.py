"""The Haylou LS02 integration."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_DEVICE_ADDRESS,
    CONF_WEATHER_SOURCE,
    DOMAIN,
    SERVICE_SEND_MESSAGE
)
from .ble_client import HaylouBLEClient, NotificationCallbacks
from .sensor import async_extract_weather_data

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["device_tracker", "sensor"]

SCAN_INTERVAL_SECONDS = 60


class HaylouUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator for Haylou LS02 watch data."""

    def __init__(self, hass: HomeAssistant, ble_client: HaylouBLEClient, config_entry: ConfigEntry):
        """Initialize coordinator.

        Manages data for a specific Haylou watch identified by MAC address.
        All data updates are based on communication with the device identified by its MAC address.
        """
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=config_entry,
            update_interval=timedelta(hours=1),
        )
        self.ble_client = ble_client  # BLE client connected to specific MAC address
        self.config_entry = config_entry
        self.data = {
            "connection_state": "disconnected",  # connected, connecting, disconnected
            "current_heart_rate": None,
            "hbm_stats": None,
            "sport_stats": None,
            "battery": None,
            "last_ble_detected": None,  # Last time device was detected in BLE scan
        }
        self._reconnect_task: Optional[asyncio.Task] = None
        self._weather_task: Optional[asyncio.Task] = None
        self._cached_weather: dict[str, Any] | None = None
        self._running = True

    async def _async_update_data(self):
        """Fetch battery level periodically."""
        if not await self.ble_client.request_battery():
            raise UpdateFailed("Failed to request battery status")
        return self.data

    async def _get_weather_payload(self) -> dict[str, Any]:
        """Fetch the current weather and next-day forecast from HA."""
        weather_entity_id = self.config_entry.options.get(
            CONF_WEATHER_SOURCE,
            self.config_entry.data.get(CONF_WEATHER_SOURCE),
        )
        if not weather_entity_id:
            return {
                "today": {
                    "weather_type": 1,
                    "current_temperature": 0,
                    "max_temperature": 0,
                    "min_temperature": 0,
                },
                "next": {
                    "weather_type": 1,
                    "max_temperature": 0,
                    "min_temperature": 0,
                },
            }

        weather_data = await async_extract_weather_data(self.hass, weather_entity_id)
        if not weather_data:
            return {
                "today": {
                    "weather_type": 1,
                    "current_temperature": 0,
                    "max_temperature": 0,
                    "min_temperature": 0,
                },
                "next": {
                    "weather_type": 1,
                    "max_temperature": 0,
                    "min_temperature": 0,
                },
            }

        self._cached_weather = weather_data
        return weather_data

    async def _send_weather_to_watch(self):
        """Send the current and next-day weather to the watch."""
        weather_payload = self._cached_weather
        if weather_payload is None:
            weather_payload = await self._get_weather_payload()

        if not weather_payload:
            return

        today = weather_payload["today"]
        next_day = weather_payload["next"]

        await self.ble_client.set_weather_today(
            today["weather_type"],
            int(today["current_temperature"]),
            int(today["max_temperature"]),
            int(today["min_temperature"]),
        )

        await self.ble_client.set_weather_next(
            next_day["weather_type"],
            int(next_day["max_temperature"]),
            int(next_day["min_temperature"]),
            next_day["weather_type"],
            int(next_day["max_temperature"]),
            int(next_day["min_temperature"]),
            next_day["weather_type"],
            int(next_day["max_temperature"]),
            int(next_day["min_temperature"]),
        )

    async def _weather_loop(self) -> None:
        """Periodic weather refresh task while connected."""
        while self._running:
            try:
                await self._get_weather_payload()
                if self.data["connection_state"] != "connected":
                    continue
                await self._send_weather_to_watch()
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.debug("Weather refresh failed: %s", err)
            await asyncio.sleep(15 * 60)

    async def async_config_entry_first_refresh(self) -> None:
        """First refresh when config entry is set up."""
        try:
            self.data["connection_state"] = "connecting"
            self.async_set_updated_data(self.data)

            # Connect to device
            if not await self.ble_client.connect():
                raise UpdateFailed("Failed to connect to Haylou watch")

            # Subscribe to notifications
            if not await self.ble_client.subscribe_notifications(
                self._notification_callbacks()
            ):
                raise UpdateFailed("Failed to subscribe to watch notifications")

            # Initialize the watch once connected
            if not await self.ble_client.initialize_watch():
                raise UpdateFailed("Failed to initialize Haylou watch")

            # Send weather at initialization if configured
            await self._get_weather_payload()
            await self._send_weather_to_watch()

            self.data["connection_state"] = "connected"
            self.data["last_ble_detected"] = datetime.now(timezone.utc)
            self.last_update_success = True
            self.async_set_updated_data(self.data)

            # Start background reconnection task
            if self._reconnect_task is None:
                self._reconnect_task = asyncio.create_task(self._ensure_connected())

            # Start periodic weather refresh task
            if self._weather_task is None:
                self._weather_task = asyncio.create_task(self._weather_loop())
        except UpdateFailed as e:
            _LOGGER.error("Update failed: %s", e)
            self.data["connection_state"] = "disconnected"
            self.async_set_updated_data(self.data)
            self.last_update_success = False
            raise

    def _notification_callbacks(self) -> NotificationCallbacks:
        """Build per-characteristic notification handlers."""
        return NotificationCallbacks(
            on_general_n1=self._on_notification_general_n1,
            on_data2_n=self._on_notification_data2_n,
        )

    def _note_ble_activity(self, characteristic: str, payload: bytes) -> None:
        """Record BLE activity and log incoming notification."""
        _LOGGER.debug(
            "Received notification from %s: %s", characteristic, payload.hex()
        )
        self.data["last_ble_detected"] = datetime.now(timezone.utc)

    def _on_notification_general_n1(self, payload: bytes) -> None:
        """Handle incoming notification from CHAR_GENERAL_N_1."""
        self._note_ble_activity("general_n1", payload)

        battery = self.ble_client.parse_battery_status(payload)
        if battery is not None:
            self.data["battery"] = battery
            self.async_set_updated_data(self.data)
            return

        current_hr = self.ble_client.parse_hbm_status(payload)
        if current_hr is not None:
            self.data["current_heart_rate"] = current_hr
            self.async_set_updated_data(self.data)
            return

        hbm_stats = self.ble_client.parse_hbm_statistics_general_n1(payload)
        if hbm_stats is not None:
            self.data["hbm_stats"] = hbm_stats
            self.async_set_updated_data(self.data)
            return

        sport_stats = self.ble_client.parse_sport_statistics(payload)
        if sport_stats is not None:
            self.data["sport_stats"] = sport_stats
            self.async_set_updated_data(self.data)

    def _on_notification_data2_n(self, payload: bytes) -> None:
        """Handle incoming notification from CHAR_DATA2_N."""
        self._note_ble_activity("data2_n", payload)

        hbm_stats = self.ble_client.parse_hbm_statistics_data2_n(payload)
        if hbm_stats is not None:
            self.data["hbm_stats"] = hbm_stats
            self.async_set_updated_data(self.data)

        current_hr = self.ble_client.parse_hbm_status2(payload)
        if current_hr is not None:
            self.data["current_heart_rate"] = current_hr
            self.async_set_updated_data(self.data)
            return

    async def _ensure_connected(self) -> None:
        """Background task to monitor connection and auto-reconnect."""
        reconnect_delay = 5  # Start with 5 seconds
        max_reconnect_delay = 300  # Max 5 minutes

        while self._running:
            try:
                # Check if still connected
                if self.ble_client.is_connected():
                    # Reset delay on successful connection
                    reconnect_delay = 5
                    await asyncio.sleep(10)  # Check connection every 10 seconds
                    continue

                # Connection lost, attempt reconnection
                if self.data["connection_state"] != "disconnected":
                    _LOGGER.warning("Connection lost to watch, attempting to reconnect...")
                    self.data["connection_state"] = "disconnected"
                    self.async_set_updated_data(self.data)

                await asyncio.sleep(reconnect_delay)

                # Try to reconnect
                _LOGGER.info("Attempting to reconnect to watch...")
                self.data["connection_state"] = "connecting"
                self.async_set_updated_data(self.data)

                # Disconnect any existing connection
                await self.ble_client.disconnect()
                await asyncio.sleep(1)

                # Reconnect
                if not await self.ble_client.connect():
                    _LOGGER.warning("Failed to reconnect, retrying in %d seconds", reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
                    continue

                # Subscribe to notifications
                if not await self.ble_client.subscribe_notifications(
                    self._notification_callbacks()
                ):
                    _LOGGER.warning("Failed to subscribe to notifications")
                    await self.ble_client.disconnect()
                    reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
                    continue

                # Re-initialize watch
                if not await self.ble_client.initialize_watch():
                    _LOGGER.warning("Failed to initialize watch after reconnection")
                    await self.ble_client.disconnect()
                    reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
                    continue

                # Successful reconnection
                _LOGGER.info("Successfully reconnected to watch")
                self.data["connection_state"] = "connected"
                self.data["last_ble_detected"] = datetime.now(timezone.utc)
                self.last_update_success = True
                self.async_set_updated_data(self.data)
                reconnect_delay = 5  # Reset delay

            except asyncio.CancelledError:
                break
            except Exception as e:
                _LOGGER.error("Error in reconnect loop: %s", e)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)

    async def async_shutdown(self) -> None:
        """Shutdown coordinator and disconnect."""
        self._running = False
        if self._weather_task:
            self._weather_task.cancel()
            try:
                await self._weather_task
            except asyncio.CancelledError:
                pass
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        await self.ble_client.disconnect()
        self.data["connection_state"] = "disconnected"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up config entry."""
    _LOGGER.debug("Setting up entry for device: %s", entry.data[CONF_DEVICE_ADDRESS])

    # Initialize coordinator
    ble_client = HaylouBLEClient(hass, entry.data[CONF_DEVICE_ADDRESS])
    coordinator = HaylouUpdateCoordinator(hass, ble_client, entry)

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

    # Set up entities
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services once for the domain
    _async_setup_services(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    return True


@callback
def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options updates."""
    hass.async_create_task(_async_apply_options(hass, entry))


async def _async_apply_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Refresh weather after the user changes integration options."""
    if DOMAIN not in hass.data or entry.entry_id not in hass.data[DOMAIN]:
        return

    coordinator: HaylouUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    await coordinator._get_weather_payload()
    if coordinator.data.get("connection_state") == "connected":
        await coordinator._send_weather_to_watch()


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
                _async_unload_services(hass)
        return unload_ok

    return False


SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required("message"): cv.string,
        vol.Optional("message_type", default="generic"): cv.string,
        vol.Optional(CONF_DEVICE_ADDRESS): cv.string,
    }
)


def _get_ble_client_for_call(hass: HomeAssistant, call: ServiceCall) -> HaylouBLEClient:
    """Resolve the BLE client targeted by a service call."""
    if DOMAIN not in hass.data or not hass.data[DOMAIN]:
        raise HomeAssistantError("Haylou LS02 integration is not loaded")

    requested_address = call.data.get(CONF_DEVICE_ADDRESS)
    if requested_address:
        requested_address = requested_address.upper()
        for entry_data in hass.data[DOMAIN].values():
            entry = entry_data["coordinator"].config_entry
            if entry.data[CONF_DEVICE_ADDRESS].upper() == requested_address:
                return entry_data["ble_client"]
        raise HomeAssistantError(f"No Haylou watch found at address {requested_address}")

    if len(hass.data[DOMAIN]) == 1:
        return next(iter(hass.data[DOMAIN].values()))["ble_client"]

    raise HomeAssistantError(
        "Multiple Haylou watches are configured; specify device_address in the service call"
    )


def _async_setup_services(hass: HomeAssistant) -> None:
    """Set up integration services."""

    async def send_message_handler(call: ServiceCall) -> None:
        """Handle send_message service call."""
        message = call.data["message"]
        msg_type = call.data.get("message_type", "generic")
        ble_client = _get_ble_client_for_call(hass, call)
        device_address = ble_client.device_address

        _LOGGER.debug("Sending message to %s: %s", device_address, message)

        success = await ble_client.send_message(message, msg_type)
        if not success:
            raise HomeAssistantError(f"Failed to send message to {device_address}")

    if hass.services.has_service(DOMAIN, SERVICE_SEND_MESSAGE):
        return

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_MESSAGE,
        send_message_handler,
        schema=SEND_MESSAGE_SCHEMA,
    )
    _LOGGER.debug("Registered %s.%s service", DOMAIN, SERVICE_SEND_MESSAGE)


def _async_unload_services(hass: HomeAssistant) -> None:
    """Remove integration services when the last config entry is unloaded."""
    if hass.services.has_service(DOMAIN, SERVICE_SEND_MESSAGE):
        hass.services.async_remove(DOMAIN, SERVICE_SEND_MESSAGE)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Migrate an old config entry."""
    _LOGGER.debug("Migrating config entry from version %s", config_entry.version)

    if config_entry.version == 1:
        # Current version, no migration needed
        return True

    return False
