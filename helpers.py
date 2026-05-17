"""Helper classes for the Haylou Watch"""

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

    def timestamp(self) -> datetime | None:
        if self.year < 1 or self.month < 1 or self.day < 1:
            return None

        return datetime(
            self.year, self.month, self.day,
            self.hour, self.minute, self.second,
            tzinfo=timezone.utc
        )


class HaylouSteps:
    """Helper struct to track steps count"""

    def __init__(self):
        """Set initial values"""
        self._adding_stored = False
        self._base_value = 0
        self._last_value = 0
        self._previous_value = 0
        self._last_time = HaylouTime()

    def set_value_incremental(self, time: HaylouTime, steps: int):
        if self._last_time != time:
            self._last_time = time
            self._base_value += self._last_value
        self._last_value = steps

    def add_value_stored(self, time: HaylouTime, steps: int):
        if not self._adding_stored:
            self._previous_value = self._base_value + self._last_value
            self._last_time = time
            self._base_value = 0
        elif self._last_time != time:
            self._last_time = time
            self._base_value += steps

        self._last_value = steps
        self._adding_stored = True

    def finish_adding_stored(self):
        self._adding_stored = False

    def get_value(self):
        if self._adding_stored:
            return self._previous_value
        return self._base_value + self._last_value