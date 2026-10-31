"""Deterministic standalone ZIP application for the pinned maintenance image."""

import io
import zipfile
from pathlib import Path

# Explicit runtime closure: host orchestration and credentials never enter the archive.
WORKER_MODULES = (
    "transfer_inventory.py",
    "transfer_protocol.py",
    "transfer_worker.py",
    "transfer_worker_entry.py",
)
WORKER_MAIN = b"""import sys
from transfer_protocol import require
from transfer_worker_entry import worker_main
require(len(sys.argv) == 3 and sys.argv[1] == "worker", "protocol_command")
worker_main(sys.argv[2])
"""


def worker_bundle():
    output = io.BytesIO()
    directory = Path(__file__).parent
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in (*WORKER_MODULES, "__main__.py"):
            data = WORKER_MAIN if name == "__main__.py" else (directory / name).read_bytes()
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100600 << 16
            archive.writestr(entry, data)
    return output.getvalue()
