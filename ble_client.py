"""BLE client for Haylou LS02 watch communication."""

import asyncio
import logging
from typing import Callable, Optional
from datetime import datetime, timezone
import struct

from homeassistant.components.bluetooth import BluetoothServiceInfo, async_ble_device_from_address
from homeassistant.core import HomeAssistant

from .const import (
    SERVICE_UUID,
    CHAR_WRITE_UUID,
    CHAR_NOTIFY_UUID,
    CMD_ID_ALERT_MSG,
    CMD_ID_BATTERY,
    CMD_ID_HBM_STATISTICS,
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
        self.ble_device = None
        self._client = None
        self._notification_callback: Optional[Callable] = None
        self._subscribed = False

    async def connect(self) -> bool:
        """Connect to the watch."""
        try:
            # Get BLE device from Home Assistant's Bluetooth integration
            self.ble_device = await async_ble_device_from_address(
                self.hass, self.device_address
            )
            if not self.ble_device:
                _LOGGER.error("Could not find BLE device: %s", self.device_address)
                return False

            # Import here to avoid issues if bluetooth integration not loaded
            from homeassistant.components.bluetooth import async_client_connect

            self._client = await async_client_connect(self.hass, self.ble_device)
            if not self._client:
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

    def parse_battery_status(self, payload: bytes) -> Optional[int]:
        """Parse battery status from notification payload."""
        try:
            if len(payload) >= 2 and payload[0] == CMD_ID_BATTERY:
                return payload[1]
            return None
        except Exception as e:
            _LOGGER.error("Error parsing battery status: %s", e)
            return None
