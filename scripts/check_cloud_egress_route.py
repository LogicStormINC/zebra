"""Isolated no-model cold fetch pairing; an existing SSH tunnel is diagnostic only."""

from __future__ import annotations

import ipaddress
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
from agent_runtime.web_gateway import _native_network_call
from agent_tools.web_gateway import WebGatewayRequest
from check_cloud_fetch_tls import CHILD, DETAIL, URLS

ROUTE = r"""
import ipaddress
relay_address=json.loads(os.environ['EGRESS_DIAGNOSTIC_RELAY'])
raw_connect=socket.socket.connect
def read_exact(sock,size):
 data=b''
 while len(data)<size:
  part=sock.recv(size-len(data))
  if not part:raise OSError('diagnostic SOCKS response truncated')
  data+=part
 return data
def socks_connect(sock,address):
 ip=ipaddress.ip_address(address[0])
 if not ip.is_global or ip.is_multicast or ip.is_reserved:
  raise OSError('diagnostic relay destination is not public')
 start=time.monotonic()
 try:
  raw_connect(sock,tuple(relay_address))
  sock.sendall(b'\x05\x01\x00')
  if read_exact(sock,2)!=b'\x05\x00':raise OSError('diagnostic SOCKS authentication rejected')
  atyp=b'\x01' if ip.version==4 else b'\x04'
  sock.sendall(b'\x05\x01\x00'+atyp+ip.packed+int(address[1]).to_bytes(2,'big'))
  head=read_exact(sock,4)
  if head[:3]!=b'\x05\x00\x00':raise OSError('diagnostic SOCKS connect rejected')
  if head[3]==1:size=4
  elif head[3]==4:size=16
  elif head[3]==3:size=read_exact(sock,1)[0]
  else:raise OSError('diagnostic SOCKS address type rejected')
  read_exact(sock,size+2)
  if os.environ.get('EGRESS_CANCEL_MARKERS'):
   with open(os.environ['EGRESS_CANCEL_MARKERS']+'/'+str(os.getpid()),'w') as out:
    out.write('connected')
 finally:
  rows.append(dict(stage='egress_channel',start=start,ms=(time.monotonic()-start)*1000,address=address))
socket.socket.connect=socks_connect
"""


def child_code(relay):
    return CHILD.replace(
        "scope.network_child()", (ROUTE if relay else "") + DETAIL + "\nscope.network_child()"
    )


def pair(root):
    original = subprocess.Popen
    variant = {"relay": False}
    parents = []

    def popen(args, **kwargs):
        if "native_network_scope" in args[-1]:
            args = [*args[:-1], child_code(variant["relay"])]
        start = monotonic()
        child = original(args, **kwargs)
        parents.append(dict(pid=child.pid, ms=(monotonic() - start) * 1000))
        return child

    subprocess.Popen = popen
    results = []
    try:
        for index, order in enumerate(("ABC", "CBA", "ACB", "BCA")):
            for route in order:
                relay = route != "A"
                variant["relay"] = relay
                if relay:
                    os.environ["EGRESS_DIAGNOSTIC_RELAY"] = json.dumps(
                        json.loads(os.environ["EGRESS_DIAGNOSTIC_ROUTES"])[route]
                    )
                folder = root / f"{index + 1}-{route}"
                folder.mkdir()
                os.environ["DOH_COLD_TRACE"] = str(folder)
                checks = []
                scope = DohNetworkScope(lambda checks=checks: checks.append(monotonic()))

                def fetch(url, scope=scope):
                    start = monotonic()
                    try:
                        result = _native_network_call(
                            "fetch",
                            asdict(WebGatewayRequest("egress-probe", parse_web_target(url))),
                            scope,
                            timeout=6,
                        )
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

                start = monotonic()
                try:
                    with ThreadPoolExecutor(2) as pool:
                        requests = list(pool.map(fetch, URLS))
                finally:
                    scope.close()
                results.append(
                    dict(
                        pair=index + 1,
                        route=route,
                        ms=(monotonic() - start) * 1000,
                        requests=requests,
                        live_checks=len(checks),
                    )
                )
                data = dict(
                    samples=results,
                    parents=parents,
                    children=[json.loads(p.read_text()) for p in root.glob("*/*.json")],
                )
                (root / "summary.json").write_text(json.dumps(data, indent=2))
                print(json.dumps(results[-1]), flush=True)
    finally:
        subprocess.Popen = original


def selfcheck():
    """The adapter rejects blocked IPs before touching even its trusted relay."""
    import socket
    import time

    namespace = dict(socket=socket, json=json, os=os, time=time, rows=[])
    original = socket.socket.connect
    os.environ.setdefault("EGRESS_DIAGNOSTIC_RELAY", '["127.0.0.1",1]')
    try:
        exec(compile(ROUTE, "diagnostic-route", "exec"), namespace)

        class NoSocket:
            def __getattr__(self, name):
                raise AssertionError("blocked address reached socket: " + name)

        for value in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "198.18.0.1", "::1", "ff02::1"):
            try:
                namespace["socks_connect"](NoSocket(), (value, 443))
            except OSError as exc:
                assert "not public" in str(exc)
            else:
                raise AssertionError("blocked IP accepted")
        compile(child_code(True), "relay-child", "exec")
        compile(child_code(False), "normal-child", "exec")
    finally:
        socket.socket.connect = original
    print("PASS: relay destination admission and both child programs")


def cancellation(root):
    """Revoke one real tunneled request; its sibling and the SSH transport survive."""
    from threading import current_thread, local

    class ProbeRevoked(RuntimeError):
        pass

    root.mkdir(parents=True)
    markers = root / "markers"
    markers.mkdir()
    os.environ["EGRESS_CANCEL_MARKERS"] = str(markers)
    os.environ["DOH_COLD_TRACE"] = str(root)
    state, children = local(), {}
    original = subprocess.Popen

    def popen(args, **kwargs):
        if "native_network_scope" in args[-1]:
            args = [*args[:-1], child_code(True)]
        child = original(args, **kwargs)
        children[current_thread().name] = child
        return child

    def check():
        child = children.get(current_thread().name)
        if getattr(state, "revoke", False) and child and (markers / str(child.pid)).exists():
            raise ProbeRevoked("diagnostic request revoked after tunnel connect")

    subprocess.Popen = popen
    scope = DohNetworkScope(check)

    def fetch(revoke):
        state.revoke = revoke
        start = monotonic()
        try:
            result = _native_network_call(
                "fetch",
                asdict(WebGatewayRequest("cancel-probe", parse_web_target(URLS[0]))),
                scope,
                timeout=6,
            )
            assert not revoke and result["status_code"] == 200
            return dict(revoked=False, status=200, ms=(monotonic() - start) * 1000)
        except ProbeRevoked:
            assert revoke
            return dict(revoked=True, ms=(monotonic() - start) * 1000)

    try:
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(fetch, (True, False)))
    finally:
        scope.close()
        subprocess.Popen = original
        os.environ.pop("EGRESS_CANCEL_MARKERS", None)
    assert len(children) == 2 and all(child.poll() is not None for child in children.values())
    assert results[0]["revoked"] and results[1]["status"] == 200
    (root / "result.json").write_text(json.dumps(dict(results=results, reaped=2), indent=2))
    print(json.dumps(results))


def verify(path):
    data = json.loads(Path(path).read_text())
    samples = data["samples"]
    assert len(samples) == 12 and len(data["children"]) == 24
    assert [(r["pair"], r["route"]) for r in samples] == [
        (i + 1, route) for i, order in enumerate(("ABC", "CBA", "ACB", "BCA")) for route in order
    ]
    assert all(r["live_checks"] > 0 for r in samples)
    assert all(q["error"] is None and q["byte_count"] > 0 for r in samples for q in r["requests"])
    rows = [r for child in data["children"] for r in child["rows"]]
    assert sum(r["stage"] == "public_addresses" for r in rows) == 24
    assert sum(r["stage"] == "response_details" and r.get("host") == "1.1.1.1" for r in rows) == 24
    assert sum(r["stage"] == "tls_details" for r in rows) == 48
    assert sum(r["stage"] == "egress_channel" for r in rows) == 32
    print("PASS: complete balanced triples; 24 fetches/DNS responses and 48 cold TLS handshakes")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        selfcheck()
    elif len(sys.argv) == 3 and sys.argv[1] == "--verify":
        verify(sys.argv[2])
    elif "--cancel" in sys.argv:
        cancellation(Path(os.environ["EGRESS_DIAGNOSTIC_OUTPUT"]))
    else:
        root = Path(os.environ["EGRESS_DIAGNOSTIC_OUTPUT"])
        routes = json.loads(os.environ["EGRESS_DIAGNOSTIC_ROUTES"])
        assert set(routes) == {"B", "C"}
        for address, port in routes.values():
            ipaddress.ip_address(address)
            assert isinstance(port, int) and 0 < port < 65536
        root.mkdir(parents=True)
        pair(root)
