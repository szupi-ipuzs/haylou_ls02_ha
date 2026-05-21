"""Helper classes for the Haylou Watch"""

import logging
from datetime import datetime
from enum import Enum
from typing import Any

from homeassistant.util import dt as dt_util

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
        """Build HaylouTime from a datetime using the Home Assistant local timezone."""
        local = dt_util.as_local(ts)
        result = HaylouTime()
        result.year = local.year & 0xFFFF
        result.month = local.month & 0xFF
        result.day = local.day & 0xFF
        result.hour = local.hour & 0xFF
        result.minute = local.minute & 0xFF
        result.second = local.second & 0xFF
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
        """Return naive wall-clock time as reported by the watch (no timezone)."""
        if self.year < 1 or self.month < 1 or self.day < 1:
            return None

        return datetime(
            self.year,
            self.month,
            self.day,
            self.hour,
            self.minute,
            self.second,
        )

    def timestamp_utc(self) -> datetime | None:
        """Convert watch wall-clock time to UTC for Home Assistant."""
        naive = self.timestamp()
        if naive is None:
            return None
        return dt_util.as_utc(dt_util.as_local(naive))

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


class _ParserState:
    AWAIT_NONDATA_FRAME = 0
    AWAIT_DATA_FRAME = 1


class HaylouSleepType(Enum):
    """Sleep stage reported by the watch."""

    DEEP = "deep"
    LIGHT = "light"

    @classmethod
    def from_wire_byte(cls, value: int) -> "HaylouSleepType":
        """Map the stage byte from a sleep data record."""
        return cls.DEEP if value == 0x01 else cls.LIGHT


class HaylouSleepPeriod:
    """A single parsed sleep segment."""

    def __init__(
        self,
        start: HaylouTime,
        stage: HaylouSleepType,
        duration: int,
    ) -> None:
        self.start = start
        self.type = stage
        self.duration = duration


class HaylouSleep:
    """Accumulate and parse a Haylou sleep sync burst (init, data, end frames).

    The watch may send multiple init/data pairs before the final end marker.
    Each exported period dict contains ``start`` (UTC datetime for HA), ``type``
    (``deep`` or ``light``), and ``duration`` (minutes, minimum 1).
    """

    INIT_FRAME_LENGTH = 7
    END_FRAME_LENGTH = 2
    PERIOD_RECORD_SIZE = 6

    def __init__(self) -> None:
        """Initialize an empty sleep sync session."""
        self._frames: list[bytes] = []
        self._periods: list[HaylouSleepPeriod] = []
        _LOGGER.debug("HaylouSleep session started")

    def store_frame(self, payload: bytes) -> None:
        """Store one sleep sync frame (header, data, or end)."""
        self._frames.append(payload)
        _LOGGER.debug(
            "Sleep frame stored (%d bytes, total=%d): %s",
            len(payload),
            len(self._frames),
            payload.hex(" "),
        )

    def parse(self) -> bool:
        """Parse all stored frames. Returns True only when a valid end frame is seen."""
        _LOGGER.debug("Parsing sleep session (%d frame(s))", len(self._frames))

        if not self._frames:
            _LOGGER.warning("Sleep parse aborted: no frames to parse")
            return False

        state = _ParserState.AWAIT_NONDATA_FRAME
        time_from_header: HaylouTime | None = None
        number_of_periods_from_header = 0
        saw_end_frame = False

        for frame in self._frames:
            if state == _ParserState.AWAIT_NONDATA_FRAME:
                if self._is_header_frame(frame):
                    parsed_header = self._parse_header_frame(frame)
                    if parsed_header is None:
                        _LOGGER.warning(
                            "Sleep parse aborted: invalid header frame: %s",
                            frame.hex(" "),
                        )
                        return False

                    time_from_header, number_of_periods_from_header = parsed_header
                    header_ts = time_from_header.timestamp()
                    _LOGGER.debug(
                        "Sleep header: date=%s expected_periods=%d",
                        header_ts,
                        number_of_periods_from_header,
                    )
                    if number_of_periods_from_header > 0:
                        state = _ParserState.AWAIT_DATA_FRAME
                    continue

                if self._is_end_frame(frame):
                    saw_end_frame = True
                    _LOGGER.debug("Sleep end frame received")
                    break

                _LOGGER.warning(
                    "Sleep parse aborted: unexpected frame while awaiting header/end: %s",
                    frame.hex(" "),
                )
                return False

            if state == _ParserState.AWAIT_DATA_FRAME:
                if time_from_header is None:
                    _LOGGER.warning("Sleep parse aborted: data frame before header")
                    return False

                if self._is_end_frame(frame):
                    _LOGGER.warning(
                        "Sleep end received before data frame (expected %d period(s))",
                        number_of_periods_from_header,
                    )
                    saw_end_frame = True
                    break

                if self._is_header_frame(frame):
                    _LOGGER.warning(
                        "Sleep parse aborted: new header before data frame: %s",
                        frame.hex(" "),
                    )
                    return False

                parsed_periods = self._parse_data_frame(
                    time_from_header,
                    number_of_periods_from_header,
                    frame,
                )
                if parsed_periods is None:
                    _LOGGER.warning(
                        "Sleep parse aborted: invalid data frame: %s",
                        frame.hex(" "),
                    )
                    return False

                self._periods.extend(parsed_periods)
                self._log_period_batch(parsed_periods)
                state = _ParserState.AWAIT_NONDATA_FRAME
                time_from_header = None
                number_of_periods_from_header = 0
                continue

            # Defensive: unknown state should never happen (no infinite loop).
            _LOGGER.error("Sleep parse aborted: invalid parser state %s", state)
            return False

        if not saw_end_frame:
            _LOGGER.warning("Sleep parse aborted: end frame missing")
            return False

        deep_minutes = sum(
            p.duration for p in self._periods if p.type == HaylouSleepType.DEEP
        )
        light_minutes = sum(
            p.duration for p in self._periods if p.type == HaylouSleepType.LIGHT
        )
        _LOGGER.info(
            "Sleep sync complete: %d period(s), deep=%d min, light=%d min, total=%d min",
            len(self._periods),
            deep_minutes,
            light_minutes,
            deep_minutes + light_minutes,
        )
        return True

    @staticmethod
    def _copy_day(base: HaylouTime) -> HaylouTime:
        """Copy year/month/day from a header date into a new HaylouTime."""
        day = HaylouTime()
        day.year = base.year
        day.month = base.month
        day.day = base.day
        return day

    def _log_period_batch(self, periods: list[HaylouSleepPeriod]) -> None:
        """Log one parsed data chunk."""
        deep_minutes = sum(
            p.duration for p in periods if p.type == HaylouSleepType.DEEP
        )
        light_minutes = sum(
            p.duration for p in periods if p.type == HaylouSleepType.LIGHT
        )
        _LOGGER.info(
            "Sleep chunk parsed: %d period(s), deep=%d min, light=%d min",
            len(periods),
            deep_minutes,
            light_minutes,
        )
        for index, period in enumerate(periods):
            _LOGGER.debug(
                "  period[%d]: start=%s type=%s duration=%d min",
                index,
                period.start.timestamp(),
                period.type.value,
                period.duration,
            )

    def _is_header_frame(self, payload: bytes) -> bool:
        return (
            len(payload) == self.INIT_FRAME_LENGTH
            and payload[0] == CMD_ID_SLEEP_FETCH
            and payload[1] == SLEEP_FETCH_SUBCMD_INIT
        )

    def _is_end_frame(self, payload: bytes) -> bool:
        return (
            len(payload) == self.END_FRAME_LENGTH
            and payload[0] == CMD_ID_SLEEP_FETCH
            and payload[1] == SLEEP_FETCH_SUBCMD_END
        )

    def _parse_header_frame(self, payload: bytes) -> tuple[HaylouTime, int] | None:
        """Parse the header frame into session date and expected period count."""
        if not self._is_header_frame(payload):
            return None

        return (
            HaylouTime.from_payload(payload[2:6]),
            payload[6],
        )

    def _parse_data_frame(
        self,
        start_date: HaylouTime,
        number_of_periods: int,
        payload: bytes,
    ) -> list[HaylouSleepPeriod] | None:
        """Parse one 0x1E data frame into sleep periods."""
        expected_length = 1 + self.PERIOD_RECORD_SIZE * number_of_periods
        if len(payload) < expected_length:
            _LOGGER.debug(
                "Data frame too short: need %d bytes, got %d",
                expected_length,
                len(payload),
            )
            return None

        if payload[0] != CMD_ID_SLEEP_DATA:
            _LOGGER.debug(
                "Data frame command mismatch: expected 0x%02X, got 0x%02X",
                CMD_ID_SLEEP_DATA,
                payload[0],
            )
            return None

        periods: list[HaylouSleepPeriod] = []
        for offset in range(1, expected_length, self.PERIOD_RECORD_SIZE):
            period_start = self._copy_day(start_date)
            period_start.hour = payload[offset]
            period_start.minute = payload[offset + 1]
            stage = HaylouSleepType.from_wire_byte(payload[offset + 2])
            raw_duration = payload[offset + 5]
            duration = 1 if raw_duration == 0 else raw_duration
            periods.append(HaylouSleepPeriod(period_start, stage, duration))

        if len(periods) != number_of_periods:
            _LOGGER.warning(
                "Period count mismatch: header expected %d, parsed %d",
                number_of_periods,
                len(periods),
            )

        return periods

    def get_periods_for_date(self, haylou_time: HaylouTime) -> list[dict[str, Any]]:
        """Return period dicts whose start falls on the same calendar day."""
        result: list[dict[str, Any]] = []
        for period in self._periods:
            if not period.start.is_same_day(haylou_time):
                continue
            start = period.start.timestamp_utc()
            if start is None:
                _LOGGER.warning("Skipping sleep period with invalid start time")
                continue
            result.append(
                {
                    "start": start,
                    "type": period.type.value,
                    "duration": period.duration,
                }
            )
        return result
