"""Helper classes for the Haylou Watch"""

import logging
from datetime import datetime, timezone
from typing import Any

from .const import (
    CMD_ID_SLEEP_DATA,
    CMD_ID_SLEEP_FETCH,
    SLEEP_FETCH_SUBCMD_END,
    SLEEP_FETCH_SUBCMD_INIT,
)

_LOGGER = logging.getLogger(__name__)

class HaylouTime:
    def __init__(self):
        self.clear()

    def clear(self):
        self.year = 0
        self.month = 0
        self.day = 0
        self.hour = 0
        self.minute = 0
        self.second = 0

    @staticmethod
    def from_datetime(ts: datetime) -> HaylouTime:
        result = HaylouTime()
        result.year = ts.year & 0xFFFF
        result.month = ts.month & 0xFF
        result.day = ts.day & 0xFF
        result.hour = ts.hour & 0xFF
        result.minute = ts.minute & 0xFF
        result.second = ts.second & 0xFF
        return result

    @staticmethod
    def from_payload(payload: bytes) -> HaylouTime:
        result = HaylouTime()
        length = len(payload)

        if length >= 2:
            result.year = (payload[0] << 8) | payload[1]
        if length >= 3:
            result.month = payload[2]
        if length >= 4:
            result.day = payload[3]
        if length >= 5:
            result.hour = payload[4]
        if length >= 6:
            result.minute = payload[5]
        if length >= 7:
            result.second = payload[6]
        return result

    def __eq__(self, other):
        if not isinstance(other, HaylouTime):
            return False
        return (self.year == other.year and
                self.month == other.month and
                self.day == other.day and
                self.hour == other.hour and
                self.minute == other.minute and
                self.second == other.second)

    def __hash__(self):
        return hash((self.year, self.month, self.day, self.hour, self.minute, self.second))

    def timestamp(self) -> datetime | None:
        if self.year < 1 or self.month < 1 or self.day < 1:
            return None

        return datetime(
            self.year, self.month, self.day,
            self.hour, self.minute, self.second,
            tzinfo=timezone.utc
        )

    def is_same_day(self, other: HaylouTime) -> bool:
        return self.year == other.year and self.month == other.month and self.day == other.day

    def is_same_hour(self, other: HaylouTime) -> bool:
        return self.is_same_day(other) and self.hour == other.hour

    def to_payload(self) -> bytes:
        return bytes([self.year >> 8, self.year & 0xFF, self.month, self.day, self.hour, self.minute, self.second])


class HaylouSteps:
    """Helper struct to track steps count"""

    def __init__(self):
        """Set initial values"""
        self._counters = dict[HaylouTime, int]()
        self._finished_adding = True
        self._last_returned_value = 0

    def set_value_incremental(self, time: HaylouTime, steps: int):
        self._counters[time] = steps

    def start_adding_stored(self):
        self._counters.clear()
        self._finished_adding = False

    def add_value_stored(self, time: HaylouTime, steps: int):
        if self._finished_adding:
            self._counters.clear()
            self._finished_adding = False
        self._counters[time] = steps

    def finish_adding_stored(self):
        self._finished_adding = True

    def get_value(self, time: datetime) -> int:
        if not self._finished_adding:
            return self._last_returned_value
        haylou_time = HaylouTime.from_datetime(time)
        total_steps_for_day = sum(val for key, val in self._counters.items() if key.is_same_day(haylou_time))
        self._last_returned_value = total_steps_for_day
        return total_steps_for_day


class HaylouSleep:
    """Accumulate and parse a Haylou sleep sync burst (init, data, end frames).

    Frames arrive on two BLE notify characteristics:
    - Init/end markers (0x1D) on the general data notify channel
    - Segment data (0x1E) on the sleep notify channel

    Each parsed period is a dict with:
    - ``start``: UTC ``datetime`` when the segment began
    - ``type``: ``"deep"`` or ``"light"``
    - ``duration``: length in minutes (minimum 1)
    """

    INIT_FRAME_LENGTH = 7
    END_FRAME_LENGTH = 2
    PERIOD_RECORD_SIZE = 6

    def __init__(self) -> None:
        """Initialize an empty sleep sync session."""
        self._init_frame: bytes | None = None
        self._data_frame: bytes | None = None
        self._end_frame: bytes | None = None
        _LOGGER.debug("HaylouSleep session started")

    def store_init_frame(self, payload: bytes) -> None:
        """Store the sleep sync init frame (0x1D 0x01 …)."""
        self._init_frame = payload
        _LOGGER.debug(
            "Sleep init frame stored (%d bytes): %s",
            len(payload),
            payload.hex(" "),
        )

    def store_data_frame(self, payload: bytes) -> None:
        """Store the sleep segment data frame (0x1E …)."""
        self._data_frame = payload
        _LOGGER.debug(
            "Sleep data frame stored (%d bytes): %s",
            len(payload),
            payload.hex(" "),
        )

    def store_end_frame(self, payload: bytes) -> None:
        """Store the sleep sync end frame (0x1D 0x02)."""
        self._end_frame = payload
        _LOGGER.debug(
            "Sleep end frame stored (%d bytes): %s",
            len(payload),
            payload.hex(" "),
        )

    def parse(self) -> list[dict[str, Any]] | None:
        """Parse accumulated frames into sleep periods.

        Returns:
            List of period dicts, an empty list when the watch reports zero
            periods, or ``None`` when required frames are missing or invalid.
        """
        _LOGGER.debug(
            "Parsing sleep session (init=%s, data=%s, end=%s)",
            self._init_frame is not None,
            self._data_frame is not None,
            self._end_frame is not None,
        )

        if self._init_frame is None:
            _LOGGER.warning("Sleep parse aborted: init frame missing")
            return None

        if self._end_frame is None:
            _LOGGER.warning("Sleep parse aborted: end frame missing")
            return None

        if not self.is_end_frame_valid():
            _LOGGER.warning(
                "Sleep parse aborted: invalid end frame (len=%s, payload=%s)",
                len(self._end_frame) if self._end_frame else 0,
                self._end_frame.hex(" ") if self._end_frame else None,
            )
            return None

        parsed_init = self._parse_init_frame()
        if parsed_init is None:
            _LOGGER.warning(
                "Sleep parse aborted: invalid init frame (len=%s, payload=%s)",
                len(self._init_frame),
                self._init_frame.hex(" "),
            )
            return None

        number_of_periods = parsed_init["number_of_periods"]
        start_date: HaylouTime = parsed_init["start_date"]
        _LOGGER.debug(
            "Sleep init parsed: date=%s, expected_periods=%d",
            start_date.timestamp(),
            number_of_periods,
        )

        if number_of_periods == 0:
            _LOGGER.info("Sleep sync completed with zero periods")
            return []

        periods = self._parse_data_frame(start_date, number_of_periods)
        if periods is None:
            _LOGGER.warning("Sleep parse aborted: data frame invalid or incomplete")
            return None

        deep_minutes = sum(
            p["duration"] for p in periods if p.get("type") == "deep"
        )
        light_minutes = sum(
            p["duration"] for p in periods if p.get("type") == "light"
        )
        _LOGGER.info(
            "Sleep sync parsed: %d period(s), deep=%d min, light=%d min, total=%d min",
            len(periods),
            deep_minutes,
            light_minutes,
            deep_minutes + light_minutes,
        )
        for index, period in enumerate(periods):
            _LOGGER.debug(
                "  period[%d]: start=%s type=%s duration=%d min",
                index,
                period.get("start"),
                period.get("type"),
                period.get("duration"),
            )
        return periods

    def _parse_init_frame(self) -> dict[str, Any] | None:
        """Parse the init frame into session date and expected period count."""
        if len(self._init_frame) != self.INIT_FRAME_LENGTH:
            _LOGGER.debug(
                "Init frame length mismatch: expected %d, got %d",
                self.INIT_FRAME_LENGTH,
                len(self._init_frame),
            )
            return None

        if self._init_frame[0] != CMD_ID_SLEEP_FETCH:
            _LOGGER.debug(
                "Init frame command mismatch: expected 0x%02X, got 0x%02X",
                CMD_ID_SLEEP_FETCH,
                self._init_frame[0],
            )
            return None

        if self._init_frame[1] != SLEEP_FETCH_SUBCMD_INIT:
            _LOGGER.debug(
                "Init frame subcommand mismatch: expected 0x%02X, got 0x%02X",
                SLEEP_FETCH_SUBCMD_INIT,
                self._init_frame[1],
            )
            return None

        return {
            "start_date": HaylouTime.from_payload(self._init_frame[2:6]),
            "number_of_periods": self._init_frame[6],
        }

    def is_end_frame_valid(self) -> bool:
        """Return whether the stored end frame matches 0x1D 0x02."""
        if self._end_frame is None:
            return False

        valid = (
            len(self._end_frame) == self.END_FRAME_LENGTH
            and self._end_frame[0] == CMD_ID_SLEEP_FETCH
            and self._end_frame[1] == SLEEP_FETCH_SUBCMD_END
        )
        if not valid:
            _LOGGER.debug(
                "End frame validation failed: len=%d payload=%s",
                len(self._end_frame),
                self._end_frame.hex(" "),
            )
        return valid

    def _parse_data_frame(
        self, start_date: HaylouTime, number_of_periods: int
    ) -> list[dict[str, Any]] | None:
        """Parse the 0x1E data frame into individual sleep periods."""
        if self._data_frame is None:
            _LOGGER.debug("Data frame missing")
            return None

        expected_length = 1 + number_of_periods * self.PERIOD_RECORD_SIZE
        if len(self._data_frame) < expected_length:
            _LOGGER.debug(
                "Data frame too short: need %d bytes, got %d",
                expected_length,
                len(self._data_frame),
            )
            return None

        if self._data_frame[0] != CMD_ID_SLEEP_DATA:
            _LOGGER.debug(
                "Data frame command mismatch: expected 0x%02X, got 0x%02X",
                CMD_ID_SLEEP_DATA,
                self._data_frame[0],
            )
            return None

        periods: list[dict[str, Any]] = []
        for offset in range(1, len(self._data_frame), self.PERIOD_RECORD_SIZE):
            period: dict[str, Any] = {}
            start_date.hour = self._data_frame[offset]
            start_date.minute = self._data_frame[offset + 1]
            period["start"] = start_date.timestamp()
            stage_byte = self._data_frame[offset + 2]
            period["type"] = "deep" if stage_byte == 0x01 else "light"
            # Duration is stored in the last byte; 0 means sub-minute (treat as 1).
            raw_duration = self._data_frame[offset + 5]
            period["duration"] = 1 if raw_duration == 0 else raw_duration
            periods.append(period)
            _LOGGER.debug(
                "  raw period @%d: hour=%d min=%d stage=0x%02X duration=%d",
                offset,
                self._data_frame[offset],
                self._data_frame[offset + 1],
                stage_byte,
                period["duration"],
            )

        if len(periods) != number_of_periods:
            _LOGGER.warning(
                "Period count mismatch: init expected %d, data frame yielded %d",
                number_of_periods,
                len(periods),
            )

        return periods
