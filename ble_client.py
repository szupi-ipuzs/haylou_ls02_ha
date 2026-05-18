"""BLE client for Haylou LS02 watch communication."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, Optional
from datetime import datetime, timezone

from homeassistant.core import HomeAssistant
from .helpers import HaylouTime, HaylouSteps

from .const import (
    CMD_ID_HBM_STATUS2,
    CMD_ID_USER_INFO,
    SERVICE_1_UUID,
    SERVICE_2_UUID,
    CHAR_GENERAL_RW_1_UUID,
    CHAR_DATA2_RW_UUID,
    CHAR_GENERAL_N_1_UUID,
    CHAR_DATA2_N_UUID,
    CMD_ID_ALERT_MSG,
    CMD_ID_BATTERY,
    CMD_ID_HBM_STATISTICS,
    CMD_ID_HBM_STATUS,
    CMD_ID_HBM_STATUS_REQUEST,
    CMD_ID_PAIR,
    CMD_ID_TIME,
    CMD_ID_UNITS,
    CMD_ID_WEATHER,
    CMD_ID_SPORT_STATISTICS,
    CMD_ID_SPORT_STATISTICS2,
    ALERT_MSG_TYPES,
)

_LOGGER = logging.getLogger(__name__)

MAX_COMMAND_LENGTH = 48
MAX_MESSAGE_CHARS = 128  # UTF-16 encoded
MAX_BATCH_CHARS = 10  # UTF-16 chars per batch
BLE_OPERATION_TIMEOUT = 3


@dataclass(frozen=True)
class NotificationCallbacks:
    """Per-characteristic notification handlers."""

    on_general_n1: Callable[[bytes], None]
    on_data2_n: Callable[[bytes], None]


class HaylouBLEClient:
    """Client for Haylou LS02 watch over BLE."""

    def __init__(self, hass: HomeAssistant, device_address: str):
        """Initialize BLE client.

        Args:
            hass: Home Assistant instance
            device_address: MAC address of the Haylou watch (e.g., "AA:BB:CC:DD:EE:FF")
        """
        self.hass = hass
        self.device_address = device_address  # MAC address of the watch
        self._client = None
        self._notification_callbacks: Optional[NotificationCallbacks] = None
        self._subscribed = False
        self._steps_counter = HaylouSteps()

    def reset_steps_counter(self) -> None:
        """Reset step aggregation state before requesting a fresh full sync."""
        self._steps_counter = HaylouSteps()

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
                await asyncio.wait_for(
                    self.unsubscribe_notifications(), timeout=BLE_OPERATION_TIMEOUT
                )
            if self._client:
                await asyncio.wait_for(
                    self._client.disconnect(), timeout=BLE_OPERATION_TIMEOUT
                )
                self._client = None
            _LOGGER.debug("Disconnected from %s", self.device_address)
        except asyncio.TimeoutError:
            _LOGGER.warning("Timed out disconnecting from %s", self.device_address)
            self._subscribed = False
            self._notification_callbacks = None
            self._client = None
        except Exception as e:
            _LOGGER.error("Error disconnecting: %s", e)

    async def subscribe_notifications(
        self, callbacks: NotificationCallbacks
    ) -> bool:
        """Subscribe to watch notifications."""
        try:
            if not self._client:
                _LOGGER.error("Not connected to device")
                return False

            self._notification_callbacks = callbacks
            await self._client.start_notify(
                CHAR_GENERAL_N_1_UUID, self._on_notification_n1
            )
            await self._client.start_notify(
                CHAR_DATA2_N_UUID, self._on_notification_data2
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
                for char_uuid in (CHAR_GENERAL_N_1_UUID, CHAR_DATA2_N_UUID):
                    try:
                        await asyncio.wait_for(
                            self._client.stop_notify(char_uuid),
                            timeout=BLE_OPERATION_TIMEOUT,
                        )
                    except asyncio.TimeoutError:
                        _LOGGER.warning(
                            "Timed out unsubscribing from %s on %s",
                            char_uuid,
                            self.device_address,
                        )
                self._subscribed = False
            self._notification_callbacks = None
            _LOGGER.debug("Unsubscribed from notifications")
        except Exception as e:
            _LOGGER.error("Error unsubscribing from notifications: %s", e)

    def _on_notification_n1(self, sender: int, data: bytes) -> None:
        """Handle incoming notification from CHAR_GENERAL_N_1."""
        if self._notification_callbacks:
            self._notification_callbacks.on_general_n1(data)

    def _on_notification_data2(self, sender: int, data: bytes) -> None:
        """Handle incoming notification from CHAR_DATA2_N."""
        if self._notification_callbacks:
            self._notification_callbacks.on_data2_n(data)

    async def send_command_1(self, cmd_data: bytes) -> bool:
        """Send a command to the watch via CHAR_GENERAL_RW_1."""
        try:
            if not self._client:
                _LOGGER.error("Not connected to device")
                return False

            if len(cmd_data) > MAX_COMMAND_LENGTH:
                _LOGGER.error(
                    "Command too long: %d > %d", len(cmd_data), MAX_COMMAND_LENGTH
                )
                return False

            await self._client.write_gatt_char(CHAR_GENERAL_RW_1_UUID, cmd_data)
            _LOGGER.debug("Sent command: %s", cmd_data.hex())
            return True
        except Exception as e:
            _LOGGER.error("Error sending command: %s", e)
            return False

    async def send_command_2(self, cmd_data: bytes) -> bool:
        """Send a command to the watch via CHAR_DATA2_RW."""
        try:
            if not self._client:
                _LOGGER.error("Not connected to device")
                return False

            if len(cmd_data) > MAX_COMMAND_LENGTH:
                _LOGGER.error(
                    "Command too long: %d > %d", len(cmd_data), MAX_COMMAND_LENGTH
                )
                return False

            await self._client.write_gatt_char(CHAR_DATA2_RW_UUID, cmd_data)
            _LOGGER.debug("Sent command: %s", cmd_data.hex())
            return True
        except Exception as e:
            _LOGGER.error("Error sending command: %s", e)
            return False

    async def request_battery(self) -> bool:
        """Request battery status from watch."""
        cmd = bytes([CMD_ID_BATTERY])
        return await self.send_command_1(cmd)

    async def request_sport_stats(self) -> bool:
        """Request sport statistics from watch."""
        cmd = bytes([CMD_ID_SPORT_STATISTICS2, 0x03, 0x01])
        return await self.send_command_1(cmd)

    async def request_hbm_stats(self) -> bool:
        """Request current HBM status from watch."""
        cmd = bytes([CMD_ID_HBM_STATUS_REQUEST, 0xFA])
        return await self.send_command_2(cmd)

    async def request_heartrate(self) -> bool:
        """Request periodic current heartrate from watch."""
        cmd = bytes([CMD_ID_HBM_STATUS_REQUEST, 0x01])
        return await self.send_command_2(cmd)

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
                if not await self.send_command_1(bytes(cmd)):
                    _LOGGER.error("Failed to send message batch %d", batch_index)
                    return False

                # Wait a bit between batches
                await asyncio.sleep(0.1)

                offset = batch_end
                batch_index += 1

            # Send finalization command
            if batch_index > 0:
                finalize_cmd = bytes([CMD_ID_ALERT_MSG, 0xFD])
                if not await self.send_command_1(finalize_cmd):
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
        success = await self.send_command_1(cmd)
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
        success = await self.send_command_1(cmd)
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
        success = await self.send_command_1(cmd)
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
        success = await self.send_command_1(cmd)
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
        success = await self.send_command_1(cmd)
        if not success:
            _LOGGER.warning("Failed to send set_weather_next command")
        return True  # Continue initialization even if command fails

    async def set_user_info(
        self,
        height_cm: int,
        weight_kg: int,
        screen_show_timeout_seconds: int,
        step_goal: int,
        lift_wrist_mode_on: bool,
        age: int,
        gender_male: bool,
    ) -> bool:
        """Set the user info on the watch."""
        cmd = bytes(
            [
                CMD_ID_USER_INFO,
                0x00,
                height_cm,
                0x00,
                weight_kg,
                screen_show_timeout_seconds,
                0x00, 0x00,
                (step_goal >> 8) & 0xFF, step_goal & 0xFF,
                0x01 if lift_wrist_mode_on else 0x00,
                0xA0, 0x00,
                age,
                0x01 if gender_male else 0x02,
            ]
        )
        success = await self.send_command_1(cmd)
        if not success:
            _LOGGER.warning("Failed to send set_user_info command")
        return True  # Continue initialization even if command fails

    async def initialize_watch(
        self,
        pairing_pin: str = "1234",
        distance_is_metric: bool = True,
        time_is_24h: bool = True,
    ) -> bool:
        """Perform the same initialization sequence as the C++ watch client."""
        try:
            # Pair with the watch
            await self.pair(pairing_pin)
            await asyncio.sleep(1.0)  # Wait for pairing response

            # Get pairing key (like C++ client does)
            pairing_key = await self.get_pairing_key(pairing_pin)
            if pairing_key:
                _LOGGER.debug("Pairing key: %s", pairing_key)
            await asyncio.sleep(0.2)

            # Set time
            await self.set_time(datetime.now())
            await asyncio.sleep(0.2)

            # Request battery status
            await self.request_battery()
            await asyncio.sleep(0.2)

            # Set units
            await self.set_units(distance_is_metric, time_is_24h)
            await asyncio.sleep(0.2)

            await self.request_sport_stats()
            await asyncio.sleep(0.5)

            await self.request_hbm_stats()
            await asyncio.sleep(0.5)

            await self.request_heartrate()

            _LOGGER.info("Watch initialization completed")
            return True
        except Exception as e:
            _LOGGER.error("Error initializing watch: %s", e)
            return False

    async def get_pairing_key(self, pin: str) -> Optional[str]:
        """Get the pairing key from the watch."""
        try:
            cmd = bytes([CMD_ID_PAIR, 0x03])
            if not await self.send_command_1(cmd):
                return None
            # Note: In a full implementation, we'd wait for the response
            # For now, just return a placeholder since we don't have response parsing
            return pin  # The PIN we used
        except Exception as e:
            _LOGGER.error("Error getting pairing key: %s", e)
            return None

    def parse_hbm_statistics_general_n1(self, payload: bytes) -> Optional[dict]:
        """Parse HBM statistics from CHAR_GENERAL_N_1 notification payload."""
        try:
            if len(payload) < 9 or payload[0] != CMD_ID_HBM_STATISTICS:
                return None

            stat_type = payload[1]

            if stat_type == 0x04 and len(payload) >= 11:
                timestamp = HaylouTime.from_payload(payload[2:8]).timestamp()
                bpm_max = payload[8]
                bpm_min = payload[9]
                bpm_avg = payload[10]

                return {
                    "timestamp": timestamp.isoformat(),
                    "bpm_min": bpm_min,
                    "bpm_avg": bpm_avg,
                    "bpm_max": bpm_max,
                    "type": "statistics1",
                }

            if stat_type == 0x03:
                timestamp = HaylouTime.from_payload(payload[2:7]).timestamp()
                bpm = payload[8]

                return {
                    "timestamp": timestamp.isoformat(),
                    "bpm": bpm,
                    "type": "statistics2",
                }

            return None
        except Exception as e:
            _LOGGER.error("Error parsing HBM statistics (general N1): %s", e)
            return None

    def parse_hbm_statistics_data2_n(self, payload: bytes) -> Optional[dict]:
        """Parse HBM statistics from CHAR_DATA2_N notification payload."""
        try:
            if payload[0] != CMD_ID_HBM_STATUS_REQUEST and len(payload) < 2:
                return None
            stat_type = payload[1]
            if (stat_type == 0x04 and len(payload) >= 11):
                timestamp = HaylouTime.from_payload(payload[2:7]).timestamp()
                bpm_max = payload[8]
                bpm_min = payload[9]
                bpm_avg = payload[10]

                return {
                    "timestamp": timestamp.isoformat(),
                    "bpm_min": bpm_min,
                    "bpm_avg": bpm_avg,
                    "bpm_max": bpm_max,
                    "type": "statistics1",
                }
            elif (stat_type == 0x03 and len(payload) >= 9):
                timestamp = HaylouTime.from_payload(payload[2:8]).timestamp()
                bpm = payload[8]

                return {
                    "timestamp": timestamp.isoformat(),
                    "bpm": bpm,
                    "type": "statistics2",
                }
            else:
                return None

        except Exception as e:
            _LOGGER.error("Error parsing HBM statistics (data2 N): %s", e)
            return None

    def parse_heartrate_data2_n(self, payload: bytes) -> Optional[int]:
        """Parse heartrate from CHAR_DATA2_N notification payload."""
        try:
            if len(payload) < 4 or payload[0] != CMD_ID_HBM_STATUS2 or payload[1] != 0x11:
                return None

            return payload[3]
        except Exception as e:
            _LOGGER.error("Error parsing heartrate (data2 N): %s", e)
            return None

    def parse_sport_statistics(self, payload: bytes) -> Optional[dict]:
        """Parse sport statistics (both frame types) from notification payload."""
        try:
            if len(payload) < 1:
                return None
            if payload[0] == CMD_ID_SPORT_STATISTICS:
                return self.parse_sport_statistics1(payload)
            if payload[0] == CMD_ID_SPORT_STATISTICS2:
                return self.parse_sport_statistics2(payload)
            return None
        except Exception as e:
            _LOGGER.error("Error parsing sports statistics: %s", e)
            return None

    def parse_sport_statistics1(self, payload: bytes) -> Optional[dict]:
        """Parse sport statistics (frame type 1) from notification payload."""
        try:
            if len(payload) < 18:
                return None

            time = HaylouTime.from_payload(payload[1:6])
            steps = (payload[6] << 8) | payload[7]
            self._steps_counter.set_value_incremental(time, steps)

            return {
                "steps_count": self._steps_counter.get_value(datetime.now())
            }

        except Exception as e:
            _LOGGER.error("Error parsing sports statistics (1): %s", e)
            return None

    def parse_sport_statistics2(self, payload: bytes) -> Optional[dict]:
        """Parse sport statistics (frame type 2) from notification payload."""
        try:
            if len(payload) == 18:
                time = HaylouTime.from_payload(payload[1:6])
                steps = (payload[6] << 8) | payload[7]
                self._steps_counter.add_value_stored(time, steps)

                return {
                    "steps_count": self._steps_counter.get_value(datetime.now())
                }
            elif (len(payload) == 3) and (payload[1] == 0xFD):
                self._steps_counter.finish_adding_stored()
                return {
                    "steps_count": self._steps_counter.get_value(datetime.now())
                }
            else:
                return None

        except Exception as e:
            _LOGGER.error("Error parsing sports statistics (2): %s", e)
            return None

    def parse_hbm_status(self, payload: bytes) -> Optional[int]:
        """Parse current HBM status from notification payload."""
        try:
            if payload[0] == CMD_ID_HBM_STATUS:
                if len(payload) < 4 or payload[1] != 0x11:
                    return None
                return payload[3]
            return None
        except Exception as e:
            _LOGGER.error("Error parsing HBM status: %s", e)
            return None

    def parse_hbm_status2(self, payload: bytes) -> Optional[int]:
        """Parse current HBM status from notification payload."""
        try:
            if payload[0] == CMD_ID_HBM_STATUS2:
                if len(payload) < 4 or payload[1] != 0x11:
                    return None
                return payload[3]
            if payload[0] == CMD_ID_HBM_STATUS_REQUEST:
                if len(payload) < 9 or payload[1] != 0x03:
                    return None
                return payload[8]
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
