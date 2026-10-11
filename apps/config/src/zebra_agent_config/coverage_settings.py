"""Bounded scheduling slices; task admission still owns execution budgets."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class CoverageWorkSettings:
    max_units: int = 32
    max_input_bytes: int = 8 * 1024 * 1024
    max_milliseconds: int = 2000

    def __post_init__(self) -> None:
        for value, ceiling in (
            (self.max_units, 1000),
            (self.max_input_bytes, 32 * 1024 * 1024),
            (self.max_milliseconds, 60000),
        ):
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError("invalid coverage work slice")


def load_coverage_work(values: Mapping[str, str]) -> CoverageWorkSettings:
    return CoverageWorkSettings(
        max_units=int(values.get("ZEBRA_COVERAGE_WORK_UNITS", "32")),
        max_input_bytes=int(values.get("ZEBRA_COVERAGE_WORK_INPUT_BYTES", "8388608")),
        max_milliseconds=int(values.get("ZEBRA_COVERAGE_WORK_MILLISECONDS", "2000")),
    )
