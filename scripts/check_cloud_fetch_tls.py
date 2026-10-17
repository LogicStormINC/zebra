"""No-model matched actual fetches; reuse the existing isolated child observer."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from time import monotonic

from agent_core.domain.web import parse_web_target
from agent_runtime.native_network_scope import DohNetworkScope
from agent_runtime.web_gateway import _native_network_call, sticky_network_cancellation_check
from agent_tools.web_gateway import WebGatewayRequest
from check_cloud_doh_cold import CHILD

DETAIL = r"""
import struct
def tcp_info(sock):
 # Linux UAPI tcp_info: 8 byte prefix then original 24 uint32 fields.
 data=sock.getsockopt(socket.IPPROTO_TCP,socket.TCP_INFO,104)
 values=struct.unpack_from('=24I',data,8)
 return dict(rtt_us=values[15],total_retrans=values[23])
original_connect=socket.socket.connect
def connect(sock,address):
 start=time.monotonic()
 try:return original_connect(sock,address)
 finally:
  rows.append(dict(stage='socket_connect',start=start,ms=(time.monotonic()-start)*1000,address=address))
socket.socket.connect=connect
original_tls=ssl.SSLContext.wrap_socket
def tls(context,*args,**kwargs):
 start=time.monotonic()
 cpu=time.process_time()
 secured=original_tls(context,*args,**kwargs)
 rows.append(dict(stage='tls_details',start=start,ms=(time.monotonic()-start)*1000,
  cpu_ms=(time.process_time()-cpu)*1000,host=kwargs.get('server_hostname'),
  peer=secured.getpeername(),version=secured.version(),tcp=tcp_info(secured),
  cipher=secured.cipher(),reused=secured.session_reused,alpn=secured.selected_alpn_protocol()))
 return secured
ssl.SSLContext.wrap_socket=tls
original_response=http.client.HTTPConnection.getresponse
def response(connection,*args,**kwargs):
 cpu=time.process_time()
 result=original_response(connection,*args,**kwargs)
 rows.append(dict(stage='response_details',start=time.monotonic(),ms=0,host=connection.host,
  cpu_ms=(time.process_time()-cpu)*1000,status=result.status,
  headers={key:result.getheader(key) for key in
  ('Server-Timing','Age','Cf-Cache-Status','X-Cache','Server')}))
 return result
http.client.HTTPConnection.getresponse=response
"""
URLS = (
    "https://www.postgresql.org/about/news/postgresql-18-released-3142/",
    "https://redis.io/blog/redis-8-ga/",
)


def main():
    root = Path(os.environ["DOH_COLD_TRACE"])
    root.mkdir(parents=True, exist_ok=True)
    original = subprocess.Popen
    starts = []

    def popen(args, **kwargs):
        if "native_network_scope" in args[-1] or "_network_child" in args[-1]:
            child_code = CHILD.replace("scope.network_child()", DETAIL + "\nENTRY()")
            entry = (
                "scope.network_child"
                if "native_network_scope" in args[-1]
                else "web._network_child"
            )
            child_code = child_code.replace("ENTRY()", entry + "()")
            args = [*args[:-1], child_code]
        start = monotonic()
        child = original(args, **kwargs)
        starts.append(dict(pid=child.pid, start=start, ms=(monotonic() - start) * 1000))
        return child

    subprocess.Popen = popen
    samples = []
    try:
        for pair in range(4):
            for enabled in (False, True) if pair % 2 == 0 else (True, False):
                checks = []
                check = sticky_network_cancellation_check(
                    lambda checks=checks: checks.append(monotonic()), reuse_doh=enabled
                )
                row = dict(pair=pair + 1, enabled=enabled)

                def fetch(url, check=check):
                    start = monotonic()
                    request = WebGatewayRequest("probe", parse_web_target(url))
                    try:
                        result = _native_network_call("fetch", asdict(request), check, timeout=6)
                        assert result["status_code"] == 200 and result["byte_count"] > 0
                        return dict(
                            url=url,
                            ms=(monotonic() - start) * 1000,
                            error=None,
                            byte_count=result["byte_count"],
                        )
                    except Exception as exc:
                        return dict(
                            url=url,
                            ms=(monotonic() - start) * 1000,
                            error=type(exc).__name__ + ": " + str(exc),
                        )

                try:
                    for batch in ("cold", "followup"):
                        start = monotonic()
                        with ThreadPoolExecutor(2) as pool:
                            requests = list(pool.map(fetch, URLS))
                        row[batch] = dict(ms=(monotonic() - start) * 1000, requests=requests)
                    row["live_checks"] = len(checks)
                finally:
                    if isinstance(check, DohNetworkScope):
                        check.close()
                samples.append(row)
                (root / "summary.json").write_text(
                    json.dumps(
                        dict(
                            samples=samples,
                            parents=starts,
                            children=[json.loads(p.read_text()) for p in root.glob("[0-9]*.json")],
                        ),
                        indent=2,
                    )
                )
                print(json.dumps(row), flush=True)
    finally:
        subprocess.Popen = original


def verify(path):
    """Offline check of a complete fixed cohort, including all unsuccessful samples."""
    data = json.loads(Path(path).read_text())
    samples, children = data["samples"], data["children"]
    assert len(samples) == 8 and len(children) == 24
    assert [(r["pair"], r["enabled"]) for r in samples] == [
        (1, False),
        (1, True),
        (2, True),
        (2, False),
        (3, False),
        (3, True),
        (4, True),
        (4, False),
    ]
    assert all(r["live_checks"] > 0 for r in samples)
    requests = [q for r in samples for batch in ("cold", "followup") for q in r[batch]["requests"]]
    assert len(requests) == 32 and all(q["error"] is None for q in requests)
    assert all(q["byte_count"] > 0 for q in requests)
    rows = [r for c in children for r in c["rows"]]
    assert sum(r["stage"] == "public_addresses" for r in rows) == 32
    for host, expected_tls in (("1.1.1.1", 24), ("redis.io", 16), ("www.postgresql.org", 16)):
        assert (
            sum(r["stage"] == "tls_details" and r.get("host") == host for r in rows) == expected_tls
        )
    assert sum(r["stage"] == "response_details" and r.get("host") == "1.1.1.1" for r in rows) == 32
    compile(
        CHILD.replace("scope.network_child()", DETAIL + "\nscope.network_child()"),
        "observed-child",
        "exec",
    )
    print("PASS: 32 successful fetches, 32 fresh DNS responses, 8 DoH handshakes avoided")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--verify":
        verify(sys.argv[2])
    else:
        main()
