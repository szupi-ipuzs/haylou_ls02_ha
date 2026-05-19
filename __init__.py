"""The Haylou LS02 integration."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothScanningMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    BLE_PRESENCE_TIMEOUT_MINUTES,
    BLE_PRESENCE_UPDATE_THROTTLE_SECONDS,
    CONF_DISTANCE_UNIT,
    CONF_DEVICE_ADDRESS,
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
    CMD_ID_SPORT_STATISTICS2,
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
    DISTANCE_UNIT_IMPERIAL,
    DOMAIN,
    LIFT_WRIST_MODE_OFF,
    SERVICE_SEND_MESSAGE,
    SPORT_STATS2_END_MARKER,
    SPORT_STATS2_MAX_CONSECUTIVE_RETRIES,
    SPORT_STATS2_RETRY_TIMEOUT_SECONDS,
    TIME_FORMAT_12H,
    USER_GENDER_FEMALE,
)
from .ble_client import HaylouBLEClient, NotificationCallbacks
from .sensor import NEXT_FORECAST_DAYS, async_extract_weather_data

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["device_tracker", "sensor", "select", "number"]

_DEFAULT_NEXT_DAY = {
    "weather_type": 1,
    "max_temperature": 0,
    "min_temperature": 0,
}


def _default_weather_payload() -> dict[str, Any]:
    """Return fallback weather data when no source entity is available."""
    next_days = [_DEFAULT_NEXT_DAY.copy() for _ in range(NEXT_FORECAST_DAYS)]
    return {
        "today": {
            "weather_type": 1,
            "current_temperature": 0,
            "max_temperature": 0,
            "min_temperature": 0,
        },
        "next": next_days[0],
        "next_days": next_days,
    }

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
        self._presence_task: Optional[asyncio.Task] = None
        self._sport_stats2_timeout_task: Optional[asyncio.Task] = None
        self._sport_stats2_in_progress = False
        self._sport_stats2_retry_pending = False
        self._sport_stats2_consecutive_retries = 0
        self._bluetooth_unsub = None
        self._cached_weather: dict[str, Any] | None = None
        self._last_presence_update_sent: datetime | None = None
        self._last_pairing_pin = self._pairing_pin()
        self._running = True

    async def _async_update_data(self):
        """Fetch battery level periodically."""
        if not await self.ble_client.request_battery():
            raise UpdateFailed("Failed to request battery status")
        return self.data

    def _time_is_24h(self) -> bool:
        """Return whether the watch should use a 24-hour time format."""
        return (
            self.config_entry.options.get(CONF_TIME_FORMAT, DEFAULT_TIME_FORMAT)
            != TIME_FORMAT_12H
        )

    def _distance_is_metric(self) -> bool:
        """Return whether the watch should use metric distance units."""
        return (
            self.config_entry.options.get(CONF_DISTANCE_UNIT, DEFAULT_DISTANCE_UNIT)
            != DISTANCE_UNIT_IMPERIAL
        )

    def _pairing_pin(self) -> str:
        """Return the configured pairing PIN."""
        pin = str(self.config_entry.options.get(CONF_PAIRING_PIN, DEFAULT_PAIRING_PIN))
        if len(pin) != 4 or not pin.isdigit():
            _LOGGER.warning("Invalid pairing PIN configured, falling back to default")
            return DEFAULT_PAIRING_PIN
        return pin

    async def async_set_watch_units(self) -> None:
        """Push configured unit preferences to the watch when connected."""
        if not self.ble_client.is_connected():
            _LOGGER.debug("Skipping unit update because watch is not connected")
            return

        await self.ble_client.set_units(
            distance_is_metric=self._distance_is_metric(),
            time_is_24h=self._time_is_24h(),
        )

    def _user_height_cm(self) -> int:
        """Return configured user height in centimeters."""
        return int(
            self.config_entry.options.get(
                CONF_USER_HEIGHT_CM,
                DEFAULT_USER_HEIGHT_CM,
            )
        )

    def _user_weight_kg(self) -> int:
        """Return configured user weight in kilograms."""
        return int(
            self.config_entry.options.get(
                CONF_USER_WEIGHT_KG,
                DEFAULT_USER_WEIGHT_KG,
            )
        )

    def _user_age(self) -> int:
        """Return configured user age."""
        return int(self.config_entry.options.get(CONF_USER_AGE, DEFAULT_USER_AGE))

    def _screen_show_timeout_seconds(self) -> int:
        """Return configured screen timeout in seconds."""
        return int(
            self.config_entry.options.get(
                CONF_SCREEN_SHOW_TIMEOUT_SECONDS,
                DEFAULT_SCREEN_SHOW_TIMEOUT_SECONDS,
            )
        )

    def _step_goal(self) -> int:
        """Return configured daily step goal."""
        return int(self.config_entry.options.get(CONF_STEP_GOAL, DEFAULT_STEP_GOAL))

    def _user_gender_male(self) -> bool:
        """Return whether the configured user gender is male."""
        return (
            self.config_entry.options.get(CONF_USER_GENDER, DEFAULT_USER_GENDER)
            != USER_GENDER_FEMALE
        )

    def _lift_wrist_mode_on(self) -> bool:
        """Return whether lift wrist mode is enabled."""
        return (
            self.config_entry.options.get(
                CONF_LIFT_WRIST_MODE,
                DEFAULT_LIFT_WRIST_MODE,
            )
            != LIFT_WRIST_MODE_OFF
        )

    async def async_set_user_info(self) -> None:
        """Push configured user info to the watch when connected."""
        if not self.ble_client.is_connected():
            _LOGGER.debug("Skipping user info update because watch is not connected")
            return

        await self.ble_client.set_user_info(
            height_cm=self._user_height_cm(),
            weight_kg=self._user_weight_kg(),
            screen_show_timeout_seconds=self._screen_show_timeout_seconds(),
            step_goal=self._step_goal(),
            lift_wrist_mode_on=self._lift_wrist_mode_on(),
            age=self._user_age(),
            gender_male=self._user_gender_male(),
        )

    async def _get_weather_payload(self) -> dict[str, Any] | None:
        """Fetch the current weather and next-day forecast from HA."""
        weather_entity_id = self.config_entry.options.get(
            CONF_WEATHER_SOURCE,
            self.config_entry.data.get(CONF_WEATHER_SOURCE),
        )
        if not weather_entity_id:
            self._cached_weather = None
            return None

        weather_data = await async_extract_weather_data(self.hass, weather_entity_id)
        if not weather_data:
            return _default_weather_payload()

        self._cached_weather = weather_data
        return weather_data

    def _has_configured_weather_source(self) -> bool:
        """Return whether a weather entity is configured for this entry."""
        return bool(
            self.config_entry.options.get(CONF_WEATHER_SOURCE)
            or self.config_entry.data.get(CONF_WEATHER_SOURCE)
        )

    def _is_default_weather_payload(self, payload: dict[str, Any]) -> bool:
        """Return True if the payload is the integration fallback weather."""
        today = payload.get("today", {})
        next_day = payload.get("next", {})
        return (
            today.get("weather_type") == 1
            and today.get("current_temperature") == 0
            and today.get("max_temperature") == 0
            and today.get("min_temperature") == 0
            and next_day.get("weather_type") == 1
            and next_day.get("max_temperature") == 0
            and next_day.get("min_temperature") == 0
        )

    async def _send_weather_to_watch(self) -> None:
        """Send the current and next-day weather to the watch."""
        if not self._has_configured_weather_source():
            return

        weather_payload = self._cached_weather
        if weather_payload is None:
            weather_payload = await self._get_weather_payload()

        if not weather_payload:
            return

        if self._has_configured_weather_source() and self._is_default_weather_payload(
            weather_payload
        ):
            _LOGGER.warning(
                "Skipping weather sync: configured weather source returned no usable forecast"
            )
            return

        today = weather_payload["today"]
        next_days = weather_payload.get("next_days")
        if not next_days:
            next_day = weather_payload["next"]
            next_days = [next_day] * NEXT_FORECAST_DAYS

        day1, day2, day3 = next_days[:NEXT_FORECAST_DAYS]

        await self.ble_client.set_weather_today(
            today["weather_type"],
            int(today["current_temperature"]),
            int(today["max_temperature"]),
            int(today["min_temperature"]),
        )

        await self.ble_client.set_weather_next(
            day1["weather_type"],
            int(day1["max_temperature"]),
            int(day1["min_temperature"]),
            day2["weather_type"],
            int(day2["max_temperature"]),
            int(day2["min_temperature"]),
            day3["weather_type"],
            int(day3["max_temperature"]),
            int(day3["min_temperature"]),
        )

    async def _weather_loop(self) -> None:
        """Periodic weather refresh task while connected."""
        while self._running:
            try:
                if (
                    self.data["connection_state"] == "connected"
                    and self._has_configured_weather_source()
                ):
                    await self._get_weather_payload()
                    await self._send_weather_to_watch()
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.debug("Weather refresh failed: %s", err)
            await asyncio.sleep(15 * 60)

    async def _async_initialize_watch_and_weather(self) -> bool:
        """Initialize the watch and push the configured weather forecast."""
        if not await self.ble_client.initialize_watch(
            pairing_pin=self._pairing_pin(),
            distance_is_metric=self._distance_is_metric(),
            time_is_24h=self._time_is_24h(),
        ):
            return False

        await self.async_set_user_info()

        if self._has_configured_weather_source():
            # Fetch a fresh forecast after each connect/reconnect.
            self._cached_weather = None
            await self._get_weather_payload()
            await self._send_weather_to_watch()
        return True

    async def async_reconnect_now(self) -> None:
        """Disconnect and immediately reconnect using current config options."""
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None

        self.data["connection_state"] = "disconnected"
        self.async_set_updated_data(self.data)
        await self.ble_client.disconnect()

        self.data["connection_state"] = "connecting"
        self.async_set_updated_data(self.data)

        if not await self.ble_client.connect():
            _LOGGER.warning("Failed to reconnect after pairing PIN change")
            self._reconnect_task = asyncio.create_task(self._ensure_connected())
            return

        if not await self.ble_client.subscribe_notifications(
            self._notification_callbacks()
        ):
            _LOGGER.warning("Failed to subscribe after pairing PIN change")
            await self.ble_client.disconnect()
            self._reconnect_task = asyncio.create_task(self._ensure_connected())
            return

        if not await self._async_initialize_watch_and_weather():
            _LOGGER.warning("Failed to initialize after pairing PIN change")
            await self.ble_client.disconnect()
            self._reconnect_task = asyncio.create_task(self._ensure_connected())
            return

        self.data["connection_state"] = "connected"
        self.data["last_ble_detected"] = datetime.now(timezone.utc)
        self.last_update_success = True
        self.async_set_updated_data(self.data)
        self._reconnect_task = asyncio.create_task(self._ensure_connected())

    def _async_start_background_tasks(self) -> None:
        """Start background tasks for reconnection, weather, and presence."""
        self._async_setup_ble_presence()

        if self._reconnect_task is None:
            self._reconnect_task = asyncio.create_task(self._ensure_connected())

        if self._weather_task is None:
            self._weather_task = asyncio.create_task(self._weather_loop())

        if self._presence_task is None:
            self._presence_task = asyncio.create_task(self._presence_update_loop())

    async def async_config_entry_first_refresh(self) -> None:
        """Attempt initial BLE connection without blocking config entry setup."""
        self.data["connection_state"] = "connecting"
        self.async_set_updated_data(self.data)

        connected = False
        if await self.ble_client.connect():
            if await self.ble_client.subscribe_notifications(
                self._notification_callbacks()
            ):
                if await self._async_initialize_watch_and_weather():
                    connected = True
                else:
                    _LOGGER.warning(
                        "Failed to initialize Haylou watch at startup; "
                        "will retry in background"
                    )
            else:
                _LOGGER.warning(
                    "Failed to subscribe to watch notifications at startup; "
                    "will retry in background"
                )
        else:
            _LOGGER.warning(
                "Failed to connect to Haylou watch at startup; "
                "will retry in background"
            )

        if connected:
            self.data["connection_state"] = "connected"
            self.data["last_ble_detected"] = datetime.now(timezone.utc)
            self.last_update_success = True
        else:
            await self.ble_client.disconnect()
            self.data["connection_state"] = "disconnected"
            self.last_update_success = False

        self.async_set_updated_data(self.data)
        self._async_start_background_tasks()

    def _notification_callbacks(self) -> NotificationCallbacks:
        """Build per-characteristic notification handlers."""
        return NotificationCallbacks(
            on_general_n1=self._on_notification_general_n1,
            on_data2_n=self._on_notification_data2_n,
        )

    @callback
    def _mark_ble_detected(self, notify: bool = True) -> None:
        """Record that the watch was seen via BLE (connection or scan)."""
        now = datetime.now(timezone.utc)
        self.data["last_ble_detected"] = now
        should_notify = (
            notify
            and (
                self._last_presence_update_sent is None
                or (now - self._last_presence_update_sent).total_seconds()
                >= BLE_PRESENCE_UPDATE_THROTTLE_SECONDS
            )
        )
        if should_notify:
            self._last_presence_update_sent = now
            self.async_set_updated_data(self.data)

    def _async_setup_ble_presence(self) -> None:
        """Listen for passive BLE advertisements from the watch."""
        if self._bluetooth_unsub is not None:
            return

        address = self.ble_client.device_address

        @callback
        def _bluetooth_advertisement_callback(_service_info, _change) -> None:
            self._mark_ble_detected()

        self._bluetooth_unsub = bluetooth.async_register_callback(
            self.hass,
            _bluetooth_advertisement_callback,
            {"address": address},
            BluetoothScanningMode.PASSIVE,
        )

    @callback
    def _poll_ble_presence(self) -> bool:
        """Update last seen time if the watch is visible to the BLE stack."""
        address = self.ble_client.device_address
        if bluetooth.async_address_present(self.hass, address):
            self._mark_ble_detected()
            return True
        return False

    async def _presence_update_loop(self) -> None:
        """Refresh coordinator so device tracker re-evaluates the 10-minute timeout."""
        while self._running:
            try:
                if self.data.get("connection_state") != "connected":
                    if not self._poll_ble_presence():
                        self.async_set_updated_data(self.data)
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.debug("Presence refresh failed: %s", err)
            await asyncio.sleep(30)

    def _note_ble_activity(self, characteristic: str, payload: bytes) -> None:
        """Record BLE activity and log incoming notification."""
        _LOGGER.debug(
            "Received notification from %s: %s", characteristic, payload.hex()
        )
        self._mark_ble_detected(notify=False)

    def _is_sport_stats2_payload(self, payload: bytes) -> bool:
        """Return True if this notification is a sport statistics 2 frame."""
        return len(payload) >= 1 and payload[0] == CMD_ID_SPORT_STATISTICS2

    def _is_sport_stats2_end_payload(self, payload: bytes) -> bool:
        """Return True if this sport statistics 2 frame ends the current burst."""
        return len(payload) >= 2 and payload[1] == SPORT_STATS2_END_MARKER

    def _reset_sport_stats2_timeout(self) -> None:
        """Start or restart the missing-terminator timeout."""
        self._sport_stats2_in_progress = True
        if (
            self._sport_stats2_timeout_task
            and not self._sport_stats2_timeout_task.done()
        ):
            self._sport_stats2_timeout_task.cancel()
        self._sport_stats2_timeout_task = self.hass.async_create_task(
            self._retry_sport_stats_after_timeout()
        )

    def _cancel_sport_stats2_timeout(self, reset_retry_count: bool = False) -> None:
        """Cancel pending sport statistics 2 retry state."""
        self._sport_stats2_in_progress = False
        if reset_retry_count:
            self._sport_stats2_consecutive_retries = 0
        if (
            self._sport_stats2_timeout_task
            and not self._sport_stats2_timeout_task.done()
        ):
            self._sport_stats2_timeout_task.cancel()
        self._sport_stats2_timeout_task = None

    async def _retry_sport_stats_after_timeout(self) -> None:
        """Re-request sport statistics if a burst does not terminate in time."""
        try:
            await asyncio.sleep(SPORT_STATS2_RETRY_TIMEOUT_SECONDS)
            if self._sport_stats2_in_progress:
                self._sport_stats2_in_progress = False
                self._sport_stats2_timeout_task = None
                await self._request_sport_stats_retry("timeout")
        except asyncio.CancelledError:
            pass

    async def _request_sport_stats_retry(self, reason: str) -> None:
        """Request sport statistics again, guarding against duplicate retries."""
        if self._sport_stats2_retry_pending:
            return

        if (
            self._sport_stats2_consecutive_retries
            >= SPORT_STATS2_MAX_CONSECUTIVE_RETRIES
        ):
            _LOGGER.warning(
                "Not re-requesting sport statistics after %d consecutive retries",
                self._sport_stats2_consecutive_retries,
            )
            return

        self._sport_stats2_retry_pending = True
        try:
            self._sport_stats2_consecutive_retries += 1
            _LOGGER.warning("Re-requesting sport statistics: %s", reason)
            self.ble_client.reset_steps_counter()
            if not await self.ble_client.request_sport_stats():
                _LOGGER.warning("Failed to re-request sport statistics")
        finally:
            self._sport_stats2_retry_pending = False

    def _track_sport_stats2_burst(self, payload: bytes) -> None:
        """Track incomplete sport statistics 2 bursts on the N1 channel."""
        if self._is_sport_stats2_payload(payload):
            if self._is_sport_stats2_end_payload(payload):
                self._cancel_sport_stats2_timeout(reset_retry_count=True)
            else:
                self._reset_sport_stats2_timeout()
            return

        if self._sport_stats2_in_progress:
            self._cancel_sport_stats2_timeout()
            reason = (
                f"interrupted by command 0x{payload[0]:02X}"
                if payload
                else "interrupted by empty payload"
            )
            self.hass.async_create_task(
                self._request_sport_stats_retry(reason)
            )

    def _on_notification_general_n1(self, payload: bytes) -> None:
        """Handle incoming notification from CHAR_GENERAL_N_1."""
        self._note_ble_activity("general_n1", payload)
        self._track_sport_stats2_burst(payload)

        battery = self.ble_client.parse_battery_status(payload)
        if battery is not None:
            self.data["battery"] = battery
            self.async_set_updated_data(self.data)
            return

        firmware = self.ble_client.parse_firmware_version(payload)
        if firmware is not None:
            self.data["firmware"] = firmware
            device_registry = dr.async_get(self.hass)
            device = device_registry.async_get_device(
                identifiers={(DOMAIN, self.ble_client.device_address)}
            )
            if device is not None:
                device_registry.async_update_device(device.id, sw_version=firmware)
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
        
        current_hr = self.ble_client.parse_heartrate_data2_n(payload)
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

                self._poll_ble_presence()

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

                # Re-initialize watch and sync weather
                if not await self._async_initialize_watch_and_weather():
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
        if self._bluetooth_unsub:
            self._bluetooth_unsub()
            self._bluetooth_unsub = None
        if self._presence_task:
            self._presence_task.cancel()
            try:
                await self._presence_task
            except asyncio.CancelledError:
                pass
        if self._sport_stats2_timeout_task:
            self._sport_stats2_timeout_task.cancel()
            try:
                await self._sport_stats2_timeout_task
            except asyncio.CancelledError:
                pass
            self._sport_stats2_timeout_task = None
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

    # Attempt initial connection; failures are retried in the background.
    await coordinator.async_config_entry_first_refresh()

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


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options updates."""
    await _async_apply_options(hass, entry)


async def _async_apply_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply changed integration options to the watch."""
    if DOMAIN not in hass.data or entry.entry_id not in hass.data[DOMAIN]:
        return

    coordinator: HaylouUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    current_pairing_pin = coordinator._pairing_pin()
    if current_pairing_pin != coordinator._last_pairing_pin:
        _LOGGER.info("Pairing PIN changed, reconnecting watch")
        coordinator._last_pairing_pin = current_pairing_pin
        await coordinator.async_reconnect_now()
        return

    await coordinator.async_set_watch_units()
    await coordinator.async_set_user_info()
    if coordinator._has_configured_weather_source():
        await coordinator._get_weather_payload()
        if coordinator.data.get("connection_state") == "connected":
            await coordinator._send_weather_to_watch()
    else:
        coordinator._cached_weather = None


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
