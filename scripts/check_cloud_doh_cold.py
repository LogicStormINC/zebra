"""No-model profiler: actual scoped cold requests, isolated child phase traces."""

from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic

from agent_runtime.native_network_scope import DohNetworkScope
from agent_runtime.web_gateway import _native_network_call

CHILD = r"""
import time
boot=time.monotonic()
import json,os,socket,ssl,http.client
rows=[dict(stage='stdlib',start=boot,ms=(time.monotonic()-boot)*1000)]
def timed(obj,name,stage):
 original=getattr(obj,name)
 def invoke(*args,**kwargs):
  start=time.monotonic()
  try:return original(*args,**kwargs)
  finally:
   host=kwargs.get('server_hostname') or getattr(args[0] if args else None,'host',None)
   rows.append(dict(stage=stage,start=start,ms=(time.monotonic()-start)*1000,host=host))
 setattr(obj,name,invoke)
timed(socket,'getaddrinfo','system_dns')
timed(socket,'create_connection','tcp_connect')
timed(ssl,'create_default_context','ca_context')
timed(ssl.SSLContext,'wrap_socket','tls_handshake')
timed(http.client.HTTPConnection,'getresponse','response_headers')
timed(http.client.HTTPResponse,'read','body')
start=time.monotonic()
from agent_runtime import native_network_scope as scope
from agent_runtime import web_gateway as web
from agent_runtime import public_dns as dns
rows.append(dict(stage='runtime_imports',start=start,ms=(time.monotonic()-start)*1000))
timed(dns,'public_addresses','public_addresses')
from agent_runtime import mcp_http_egress as mcp
mcp.public_addresses=dns.public_addresses
original=web._execute_network_operation
def execute(*args,**kwargs):
 start=time.monotonic()
 try:return original(*args,**kwargs)
 finally:
  rows.append(dict(stage='operation',start=start,ms=(time.monotonic()-start)*1000))
  with open(os.environ['DOH_COLD_TRACE']+'/'+str(os.getpid())+'.json','w') as out:
   json.dump(dict(pid=os.getpid(),boot=boot,rows=rows),out)
web._execute_network_operation=execute
scope.network_child()
"""


def main():
    root = Path(os.environ["DOH_COLD_TRACE"])
    root.mkdir(parents=True, exist_ok=True)
    original = subprocess.Popen
    starts = []

    def popen(args, **kwargs):
        if "native_network_scope" in args[-1]:
            args = [*args[:-1], CHILD]
        start = monotonic()
        child = original(args, **kwargs)
        starts.append({"pid": child.pid, "start": start, "popen_ms": (monotonic() - start) * 1000})
        return child

    subprocess.Popen = popen
    samples = []
    try:
        for sample in range(int(os.environ.get("DOH_COLD_SAMPLES", "4"))):
            scope = DohNetworkScope(lambda: None)

            def resolve(host, scope=scope):
                start = monotonic()
                try:
                    operation = os.environ.get("DOH_COLD_OPERATION", "resolve")
                    arguments: object = host
                    if operation == "fetch":
                        from dataclasses import asdict

                        from agent_core.domain.web import parse_web_target
                        from agent_tools.web_gateway import WebGatewayRequest

                        url = (
                            "https://www.postgresql.org/about/news/postgresql-18-released-3142/"
                            if host == "www.postgresql.org"
                            else "https://redis.io/blog/redis-8-ga/"
                        )
                        arguments = asdict(WebGatewayRequest("probe", parse_web_target(url)))
                    _native_network_call(operation, arguments, scope, timeout=6)
                    error = None
                except Exception as exc:
                    error = type(exc).__name__ + ": " + str(exc)
                return {"host": host, "ms": (monotonic() - start) * 1000, "error": error}

            start = monotonic()
            try:
                with ThreadPoolExecutor(2) as pool:
                    requests = list(pool.map(resolve, ["www.postgresql.org", "redis.io"]))
                samples.append(
                    {
                        "sample": sample + 1,
                        "batch_ms": (monotonic() - start) * 1000,
                        "requests": requests,
                    }
                )
            finally:
                scope.close()
        result = {
            "samples": samples,
            "parents": starts,
            "children": [json.loads(p.read_text()) for p in root.glob("[0-9]*.json")],
        }
        (root / "summary.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    finally:
        subprocess.Popen = original


if __name__ == "__main__":
    main()
