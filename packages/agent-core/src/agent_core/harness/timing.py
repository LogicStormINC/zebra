from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from agent_core.ports.clock import ClockPort


@dataclass
class StepClock(ClockPort):
    current: datetime
    step: timedelta = timedelta(seconds=1)

    def now(self) -> datetime:
        value = self.current
        self.current = value + self.step
        return value


class SystemClock(ClockPort):
    def now(self) -> datetime:
        return datetime.now(UTC)
