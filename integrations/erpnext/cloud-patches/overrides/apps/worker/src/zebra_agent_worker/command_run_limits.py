import math


def validate_command_run_limits(batch_size, idle_sleep_seconds, configured_batch_size):
    if type(batch_size) is not int or batch_size > configured_batch_size:
        raise ValueError("worker batch exceeds configured command batch limit")
    if (
        type(idle_sleep_seconds) not in (int, float)
        or not math.isfinite(idle_sleep_seconds)
        or not 0 <= idle_sleep_seconds <= 30
    ):
        raise ValueError("worker idle interval is outside bounds")
