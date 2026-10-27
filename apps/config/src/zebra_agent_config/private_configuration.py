"""Bounded nonblocking reads of operator-mounted private configuration."""

import os
import stat


def read_private_configuration(path: str, *, max_bytes: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) not in {0o400, 0o600}:
            raise ValueError("PRIVATE_REGULAR_CONFIGURATION_REQUIRED")
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("CONFIGURATION_TOO_LARGE")
    return raw
