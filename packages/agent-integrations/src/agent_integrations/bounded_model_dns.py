"""Task-scoped DNS without uncancellable resolver threads in the model process."""

import asyncio
import ipaddress
import json
import os
import socket
import sys
from typing import Any

from agent_integrations.bounded_model_http import _NoThreadedIO

_MAX_REPLY = 65536
# Isolated stdlib-only child: no provider credentials or user PYTHONPATH.
_RESOLVER = """
import ctypes,json,os,resource,signal,socket,sys
request=json.loads(sys.stdin.buffer.read(4097))
if sys.platform == "linux":
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(1,signal.SIGKILL,0,0,0) != 0 or os.getppid() != request.pop("parent"):
        raise SystemExit(1)
    resource.setrlimit(resource.RLIMIT_AS,(128*1024**2,128*1024**2))
else:
    request.pop("parent")
resource.setrlimit(resource.RLIMIT_CPU,(2,2))
try:
    rows=socket.getaddrinfo(**request)
    if len(rows)>64:
        raise SystemExit(1)
    result={"rows":rows}
except socket.gaierror as error:
    result={"error":error.errno}
packet=json.dumps(result).encode()
if len(packet)>65536:
    raise SystemExit(1)
sys.stdout.buffer.write(packet)
"""


async def _reap(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    waiter = asyncio.create_task(process.wait())
    end = asyncio.get_running_loop().time() + 1
    cancelled = False
    while not waiter.done():
        remaining = end - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise RuntimeError("model DNS child exit unconfirmed")
        try:
            await asyncio.wait_for(asyncio.shield(waiter), remaining)
        except asyncio.CancelledError:
            cancelled = True
    waiter.result()
    if cancelled:
        raise asyncio.CancelledError


class _ModelIOLoop(asyncio.SelectorEventLoop):
    async def getaddrinfo(
        self, host: Any, port: Any, *, family: int = 0, type: int = 0,
        proto: int = 0, flags: int = 0,
    ) -> list[Any]:
        if isinstance(host, bytes):
            host = host.decode("ascii")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not isinstance(port, int) or not 0 < port <= 65535:
                raise ValueError("model DNS port is invalid")
            return socket.getaddrinfo(
                host, port, family=family, type=type, proto=proto,
                flags=flags | socket.AI_NUMERICHOST | socket.AI_NUMERICSERV,
            )
        if not isinstance(host, str) or not 0 < len(host) <= 253:
            raise ValueError("model DNS hostname is invalid")
        request = json.dumps(dict(host=host, port=port, family=family, type=type,
                                  proto=proto, flags=flags, parent=os.getpid())).encode()
        if len(request) > 4096:
            raise ValueError("model DNS request exceeds bound")
        # ponytail: one process per lookup bounds ownership; measure startup before
        # adding an explicitly scoped resolver cache or numeric remote-DNS proxy.
        spawning = asyncio.create_task(asyncio.create_subprocess_exec(
            sys.executable, "-I", "-c", _RESOLVER,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env={"PATH": os.defpath, "LANG": "C"},
        ))
        try:
            process = await asyncio.shield(spawning)
        except asyncio.CancelledError:
            while not spawning.done():
                try:
                    await asyncio.shield(spawning)
                except asyncio.CancelledError:
                    pass
            if not spawning.cancelled() and spawning.exception() is None:
                await _reap(spawning.result())
            raise
        try:
            assert process.stdin is not None and process.stdout is not None
            process.stdin.write(request)
            await process.stdin.drain()
            process.stdin.close()
            try:
                packet = await process.stdout.readexactly(_MAX_REPLY + 1)
            except asyncio.IncompleteReadError as error:
                packet = error.partial
            if len(packet) > _MAX_REPLY:
                raise ValueError("model DNS response exceeds bound")
            result = json.loads(packet)
            if "error" in result:
                raise socket.gaierror(result["error"], "bounded model DNS failed")
            rows = result["rows"]
            if not isinstance(rows, list) or not 0 < len(rows) <= 64:
                raise ValueError("model DNS response is invalid")
            return [(r[0], r[1], r[2], r[3], tuple(r[4])) for r in rows]
        finally:
            await _reap(process)


def model_io_loop() -> asyncio.AbstractEventLoop:
    loop = _ModelIOLoop()
    loop.set_default_executor(_NoThreadedIO(max_workers=1))
    return loop
