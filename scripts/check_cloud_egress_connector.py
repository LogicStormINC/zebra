"""No-model acceptance using production connector; only phase observers are injected."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import check_cloud_egress_route as route_probe
import check_cloud_fetch_tls as fetch_probe
from agent_runtime.native_network_scope import DohNetworkScope
from agent_runtime.public_egress import probe_egress
from zebra_agent_config.egress_settings import load_egress_endpoint

CONNECT_OBSERVER = r"""
original_connect_address=mcp.connect_address
def observed_connect(*args,**kwargs):
 result=original_connect_address(*args,**kwargs)
 if os.environ.get('EGRESS_CANCEL_MARKERS'):
  with open(os.environ['EGRESS_CANCEL_MARKERS']+'/'+str(os.getpid()),'w') as out:
   out.write('connected')
 return result
mcp.connect_address=observed_connect
"""


def main():
    endpoint = load_egress_endpoint(os.environ, profile="cloud")
    if endpoint is None:
        raise ValueError("an explicit prebuilt egress endpoint is required")
    # Same startup readiness as the Cloud Worker; no task or authority is retained.
    probe_egress(endpoint)
    if "--cancel" in sys.argv:
        original_scope, original_code = route_probe.DohNetworkScope, route_probe.child_code
        route_probe.DohNetworkScope = lambda check: DohNetworkScope(check, egress_endpoint=endpoint)
        route_probe.child_code = lambda _: fetch_probe.CHILD.replace(
            "scope.network_child()",
            CONNECT_OBSERVER + fetch_probe.DETAIL + "\nscope.network_child()",
        )
        try:
            route_probe.cancellation(Path(os.environ["DOH_COLD_TRACE"]))
        finally:
            route_probe.DohNetworkScope, route_probe.child_code = original_scope, original_code
    else:
        root = Path(os.environ["DOH_COLD_TRACE"])
        if (root / "summary.json").exists():
            raise ValueError("refuse to replace a completed acceptance cohort")
        original = fetch_probe.sticky_network_cancellation_check
        fetch_probe.sticky_network_cancellation_check = lambda check, reuse_doh: DohNetworkScope(
            check, egress_endpoint=endpoint if reuse_doh else None
        )
        try:
            fetch_probe.main()
        finally:
            fetch_probe.sticky_network_cancellation_check = original


def verify(path):
    data = json.loads(Path(path).read_text())
    rows, children = data["samples"], data["children"]
    assert [(r["pair"], r["enabled"]) for r in rows] == [
        (1, False),
        (1, True),
        (2, True),
        (2, False),
        (3, False),
        (3, True),
        (4, True),
        (4, False),
    ]
    assert len(children) == 16 and len(data["parents"]) == 16
    assert all(r["live_checks"] > 0 for r in rows)
    calls = [q for row in rows for b in ("cold", "followup") for q in row[b]["requests"]]
    assert len(calls) == 32 and all(q["error"] is None and q["byte_count"] > 0 for q in calls)
    traces = [r for c in children for r in c["rows"]]
    assert (
        sum(r["stage"] == "response_details" and r.get("host") == "1.1.1.1" for r in traces) == 32
    )
    assert sum(r["stage"] == "tls_details" and r.get("host") == "1.1.1.1" for r in traces) == 16
    assert (
        sum(
            r["stage"] == "tls_details" and r.get("host") in ("redis.io", "www.postgresql.org")
            for r in traces
        )
        == 32
    )
    print(
        "PASS: 32 fresh DNS/fetch results, 16 retained DoH connections, native authority callbacks"
    )


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--verify":
        verify(sys.argv[2])
    else:
        main()
