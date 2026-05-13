"""BLE client for Haylou LS02 watch communication."""

import asyncio
import logging
from typing import Callable, Optional
from datetime import datetime, timezone
import struct

from homeassistant.components.bluetooth import BluetoothServiceInfo
from homeassistant.core import HomeAssistant

from .const import (
    SERVICE_UUID,
    CHAR_WRITE_UUID,
    CHAR_NOTIFY_UUID,
    CMD_ID_ALERT_MSG,
    CMD_ID_BATTERY,
    CMD_ID_HBM_STATISTICS,
    CMD_ID_HBM_STATUS,
    CMD_ID_PAIR,
    CMD_ID_TIME,
    CMD_ID_UNITS,
    CMD_ID_WEATHER,
    ALERT_MSG_TYPES,
)

_LOGGER = logging.getLogger(__name__)

MAX_COMMAND_LENGTH = 48
MAX_MESSAGE_CHARS = 128  # UTF-16 encoded
MAX_BATCH_CHARS = 10  # UTF-16 chars per batch


class HaylouBLEClient:
    """Client for Haylou LS02 watch over BLE."""

    def __init__(self, hass: HomeAssistant, device_address: str):
        """Initialize BLE client."""
        self.hass = hass
        self.device_address = device_address
        self._client = None
        self._notification_callback: Optional[Callable] = None
        self._subscribed = False

    def is_connected(self) -> bool:
        """Check if currently connected to the watch."""
        return self._client is not None and self._client.is_connected

    async def connect(self) -> bool:
        """Connect to the watch."""
        try:
            # Use BleakScanner to resolve the device by address first
            from bleak import BleakScanner
            from bleak_retry_connector import establish_connection, BleakClientWithServiceCache

            device = await BleakScanner.find_device_by_address(self.device_address)
            if device is None:
                _LOGGER.error("Could not find BLE device: %s", self.device_address)
                return False

            self._client = await establish_connection(
                BleakClientWithServiceCache,
                device,
                device.name or self.device_address,
                max_attempts=3,
            )

            if not self._client or not self._client.is_connected:
                _LOGGER.error("Failed to connect to device: %s", self.device_address)
                return False

            _LOGGER.debug("Connected to %s", self.device_address)
            return True
        except Exception as e:
            _LOGGER.error("Error connecting to device: %s", e)
            return False

    async def disconnect(self) -> None:
        """Disconnect from the watch."""
        try:
            if self._subscribed:
                await self.unsubscribe_notifications()
            if self._client:
                await self._client.disconnect()
                self._client = None
            _LOGGER.debug("Disconnected from %s", self.device_address)
        except Exception as e:
            _LOGGER.error("Error disconnecting: %s", e)

    async def subscribe_notifications(
        self, callback: Callable[[bytes], None]
    ) -> bool:
        """Subscribe to watch notifications."""
        try:
            if not self._client:
                _LOGGER.error("Not connected to device")
                return False

            self._notification_callback = callback
            await self._client.start_notify(
                CHAR_NOTIFY_UUID, self._on_notification
            )
            self._subscribed = True
            _LOGGER.debug("Subscribed to notifications")
            return True
        except Exception as e:
            _LOGGER.error("Error subscribing to notifications: %s", e)
            return False

    async def unsubscribe_notifications(self) -> None:
        """Unsubscribe from watch notifications."""
        try:
            if self._client and self._subscribed:
                await self._client.stop_notify(CHAR_NOTIFY_UUID)
                self._subscribed = False
            self._notification_callback = None
            _LOGGER.debug("Unsubscribed from notifications")
        except Exception as e:
            _LOGGER.error("Error unsubscribing from notifications: %s", e)

    def _on_notification(self, sender: int, data: bytes) -> None:
        """Handle incoming notification from watch."""
        if self._notification_callback:
            self._notification_callback(data)

    async def send_command(self, cmd_data: bytes) -> bool:
        """Send a command to the watch."""
        try:
            if not self._client:
                _LOGGER.error("Not connected to device")
                return False

            if len(cmd_data) > MAX_COMMAND_LENGTH:
                _LOGGER.error(
                    "Command too long: %d > %d", len(cmd_data), MAX_COMMAND_LENGTH
                )
                return False

            await self._client.write_gatt_char(CHAR_WRITE_UUID, cmd_data)
            _LOGGER.debug("Sent command: %s", cmd_data.hex())
            return True
        except Exception as e:
            _LOGGER.error("Error sending command: %s", e)
            return False

    async def request_battery(self) -> bool:
        """Request battery status from watch."""
        cmd = bytes([CMD_ID_BATTERY])
        return await self.send_command(cmd)

    async def request_hbm_status(self) -> bool:
        """Request current HBM status from watch."""
        cmd = bytes([CMD_ID_HBM_STATUS])
        return await self.send_command(cmd)

    async def send_message(
        self, message: str, msg_type: str = "generic"
    ) -> bool:
        """Send a message to the watch display."""
        try:
            # Get message type ID
            msg_type_id = ALERT_MSG_TYPES.get(msg_type, ALERT_MSG_TYPES["generic"])

            # Convert to UTF-16BE (big-endian)
            message_u16 = message.encode("utf-16-be")

            # Limit total length
            if len(message_u16) > MAX_MESSAGE_CHARS * 2:
                message_u16 = message_u16[: MAX_MESSAGE_CHARS * 2]

            # Split into batches and send
            batch_index = 0
            offset = 0

            while offset < len(message_u16):
                batch_end = min(offset + MAX_BATCH_CHARS * 2, len(message_u16))
                batch_data = message_u16[offset:batch_end]

                # Build command
                cmd = bytearray([CMD_ID_ALERT_MSG, batch_index])

                # Add message type and length on first batch
                if batch_index == 0:
                    cmd.append(msg_type_id)
                    cmd.append(len(message_u16))

                # Add batch data
                cmd.extend(batch_data)

                # Send batch
                if not await self.send_command(bytes(cmd)):
                    _LOGGER.error("Failed to send message batch %d", batch_index)
                    return False

                # Wait a bit between batches
                await asyncio.sleep(0.1)

                offset = batch_end
                batch_index += 1

            # Send finalization command
            if batch_index > 0:
                finalize_cmd = bytes([CMD_ID_ALERT_MSG, 0xFD])
                if not await self.send_command(finalize_cmd):
                    _LOGGER.error("Failed to finalize message send")
                    return False

            _LOGGER.debug("Message sent successfully")
            return True
        except Exception as e:
            _LOGGER.error("Error sending message: %s", e)
            return False

    async def pair(self, pin: str = "1234") -> bool:
        """Send a pairing request to the watch."""
        if len(pin) != 4 or not pin.isdigit():
            _LOGGER.error("Pairing PIN must be 4 digits")
            return False

        cmd = bytes([CMD_ID_PAIR, 0x02]) + bytes([ord(c) for c in pin])
        success = await self.send_command(cmd)
        if not success:
            _LOGGER.warning("Failed to send pairing command, but continuing initialization")
        return True  # Don't fail initialization just because send_command returned False

    async def set_time(self, time_to_set: datetime) -> bool:
        """Set the watch time."""
        year_hi = (time_to_set.year >> 8) & 0xFF
        year_lo = time_to_set.year & 0xFF
        cmd = bytes(
            [
                CMD_ID_TIME,
                year_hi,
                year_lo,
                time_to_set.month,
                time_to_set.day,
                time_to_set.hour,
                time_to_set.minute,
                time_to_set.second,
            ]
        )
        success = await self.send_command(cmd)
        if not success:
            _LOGGER.warning("Failed to send set_time command")
        return True  # Continue initialization even if command fails

    async def set_units(
        self,
        distance_is_metric: bool = True,
        time_is_24h: bool = True,
    ) -> bool:
        """Set the watch units."""
        cmd = bytes(
            [
                CMD_ID_UNITS,
                0x01 if distance_is_metric else 0x02,
                0x01 if time_is_24h else 0x02,
            ]
        )
        success = await self.send_command(cmd)
        if not success:
            _LOGGER.warning("Failed to send set_units command")
        return True  # Continue initialization even if command fails

    def _normalize_temperature(self, temperature: int) -> int:
        """Normalize temperature for the watch weather payload."""
        if temperature >= 0:
            return temperature
        return 128 - temperature

    async def set_weather_today(
        self,
        weather_type: int,
        current_temperature: int = 8,
        max_temperature: int = 10,
        min_temperature: int = 5,
    ) -> bool:
        """Send today weather to the watch."""
        cmd = bytes(
            [
                CMD_ID_WEATHER,
                0x01,
                weather_type,
                0x00,
                self._normalize_temperature(current_temperature),
                self._normalize_temperature(max_temperature),
                self._normalize_temperature(min_temperature),
            ]
        )
        success = await self.send_command(cmd)
        if not success:
            _LOGGER.warning("Failed to send set_weather_today command")
        return True  # Continue initialization even if command fails

    async def set_weather_next(
        self,
        day1_type: int,
        day1_max: int,
        day1_min: int,
        day2_type: int,
        day2_max: int,
        day2_min: int,
        day3_type: int,
        day3_max: int,
        day3_min: int,
    ) -> bool:
        """Send next days weather forecast to the watch."""
        cmd = bytes(
            [
                CMD_ID_WEATHER,
                0x02,
                day1_type,
                0x00,
                self._normalize_temperature(day1_max),
                self._normalize_temperature(day1_min),
                day2_type,
                0x00,
                self._normalize_temperature(day2_max),
                self._normalize_temperature(day2_min),
                day3_type,
                0x00,
                self._normalize_temperature(day3_max),
                self._normalize_temperature(day3_min),
            ]
        )
        success = await self.send_command(cmd)
        if not success:
            _LOGGER.warning("Failed to send set_weather_next command")
        return True  # Continue initialization even if command fails

    async def initialize_watch(self) -> bool:
        """Perform the same initialization sequence as the C++ watch client."""
        try:
            # Pair with the watch
            await self.pair("1234")
            await asyncio.sleep(1.0)  # Wait for pairing response

            # Get pairing key (like C++ client does)
            pairing_key = await self.get_pairing_key()
            if pairing_key:
                _LOGGER.debug("Pairing key: %s", pairing_key)
            await asyncio.sleep(0.5)

            # Set time
            await self.set_time(datetime.now())
            await asyncio.sleep(0.5)

            # Request battery status
            await self.request_battery()
            await asyncio.sleep(0.5)

            # Set units
            await self.set_units(True, True)
            await asyncio.sleep(0.5)

            # Set weather for today
            await self.set_weather_today(0x09, 8, 10, 5)  # UNKNOWN_S
            await asyncio.sleep(0.5)

            # Set weather for next days
            await self.set_weather_next(
                0x06, 10, 5,  # SLIGHTLY_RAINY
                0x01, 13, 9,  # SUNNY
                0x08, 0, -2   # SNOWY
            )

            _LOGGER.info("Watch initialization completed")
            return True
        except Exception as e:
            _LOGGER.error("Error initializing watch: %s", e)
            return False

    async def get_pairing_key(self) -> Optional[str]:
        """Get the pairing key from the watch."""
        try:
            cmd = bytes([CMD_ID_PAIR, 0x03])
            if not await self.send_command(cmd):
                return None
            # Note: In a full implementation, we'd wait for the response
            # For now, just return a placeholder since we don't have response parsing
            return "1234"  # The PIN we used
        except Exception as e:
            _LOGGER.error("Error getting pairing key: %s", e)
            return None

    def parse_hbm_statistics(self, payload: bytes) -> Optional[dict]:
        """Parse HBM (heart beat monitor) statistics from notification payload."""
        try:
            if len(payload) < 11:
                return None

            if payload[0] != CMD_ID_HBM_STATISTICS:
                return None

            stat_type = payload[1]

            if stat_type == 0x04 and len(payload) >= 11:
                # Statistics format 1 (includes date/time)
                year = (payload[2] << 8) | payload[3]
                month = payload[4]
                day = payload[5]
                hour = payload[6]
                minute = payload[7]
                # second = payload[8]  # Not used in this format
                bpm_min = payload[8]
                bpm_avg = payload[9]
                bpm_max = payload[10]

                timestamp = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)

                return {
                    "timestamp": timestamp.isoformat(),
                    "bpm_min": bpm_min,
                    "bpm_avg": bpm_avg,
                    "bpm_max": bpm_max,
                    "type": "statistics1",
                }

            elif stat_type == 0x03 and len(payload) >= 9:
                # Statistics format 2 (different layout)
                year = (payload[2] << 8) | payload[3]
                month = payload[4]
                day = payload[5]
                hour = payload[6]
                minute = payload[7]
                bpm = payload[8]

                timestamp = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)

                return {
                    "timestamp": timestamp.isoformat(),
                    "bpm": bpm,
                    "type": "statistics2",
                }

            return None
        except Exception as e:
            _LOGGER.error("Error parsing HBM statistics: %s", e)
            return None

    def parse_hbm_status(self, payload: bytes) -> Optional[int]:
        """Parse current HBM status from notification payload."""
        try:
            if len(payload) >= 4 and payload[0] == CMD_ID_HBM_STATUS and payload[1] == 0x11:
                # HBM extended status response contains BPM in payload[3]
                return payload[3]
            return None
        except Exception as e:
            _LOGGER.error("Error parsing HBM status: %s", e)
            return None

    def parse_battery_status(self, payload: bytes) -> Optional[int]:
        """Parse battery status from notification payload."""
        try:
            if len(payload) >= 2 and payload[0] == CMD_ID_BATTERY:
                return payload[1]
            return None
        except Exception as e:
            _LOGGER.error("Error parsing battery status: %s", e)
            return None
