"""Private bounded NDJSON maintenance-worker entrypoint."""

import json
import sys

from transfer_protocol import Refusal, require, secure_read
from transfer_worker import Worker


def worker_main(path):
    worker = Worker(json.loads(secure_read(path)))
    allowed = {"open_snapshot", "target", "pre_restored", "copy_rows", "verify", "abort"}
    try:
        for line in sys.stdin:
            require(len(line) < 16_000_000, "protocol_bound")
            request = json.loads(line)
            command = request["command"]
            require(command in allowed, "protocol_command")
            try:
                result = getattr(worker, command)(**request.get("arguments", {}))
                print(json.dumps({"ok": True, "result": result}), flush=True)
                if command == "abort":
                    return
            except BaseException as error:
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "phase": worker.phase,
                            "sqlstate": getattr(error, "sqlstate", None),
                            "reason": str(error)
                            if isinstance(error, Refusal)
                            else "worker_failure",
                            "durable_phases": worker.durable,
                            "consumers_released": False,
                        }
                    ),
                    flush=True,
                )
                return
    finally:
        worker.abort()
