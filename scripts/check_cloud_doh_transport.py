"""Actual native dispatcher, no model: cold and reused cross-host DNS batches."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic

from agent_runtime.native_network_scope import DohNetworkScope
from agent_runtime.web_gateway import _native_network_call, sticky_network_cancellation_check


def batch(check, hosts):
    def resolve(host):
        start = monotonic()
        try:
            value = _native_network_call("resolve", host, check, timeout=6)
            assert value is None
            error = None
        except Exception as exc:
            error = type(exc).__name__ + ": " + str(exc)
        return {"host": host, "ms": round((monotonic() - start) * 1000, 3), "error": error}

    start = monotonic()
    with ThreadPoolExecutor(2) as pool:
        requests = list(pool.map(resolve, hosts))
    return {"ms": round((monotonic() - start) * 1000, 3), "requests": requests}


def main():
    rows = []
    for pair in range(4):
        for enabled in (False, True) if pair % 2 == 0 else (True, False):
            calls = []
            check = sticky_network_cancellation_check(
                lambda calls=calls: calls.append(1), reuse_doh=enabled
            )
            row = {"pair": pair + 1, "enabled": enabled}
            try:
                row["cold"] = batch(check, ["www.postgresql.org", "redis.io"])
                row["different_hosts"] = batch(check, ["www.python.org", "www.sqlite.org"])
                row["live_checks"] = len(calls)
            finally:
                if isinstance(check, DohNetworkScope):
                    check.close()
            rows.append(row)
            Path(os.environ["DOH_INTEGRATION_RESULT"]).write_text(json.dumps(rows, indent=2))
            print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
