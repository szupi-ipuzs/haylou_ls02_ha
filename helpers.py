"""Helper classes for the Haylou Watch"""

from dataclasses import dataclass
from datetime import datetime, timezone

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


class HaylouSteps:
    """Helper struct to track steps count"""

    def __init__(self):
        """Set initial values"""
        self._counters = dict[HaylouTime, int]()
        self._finished_adding = True
        self._last_returned_value = 0

    def set_value_incremental(self, time: HaylouTime, steps: int):
        self._counters[time] = steps

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
