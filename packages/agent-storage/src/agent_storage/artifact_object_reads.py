"""Immutable S3 reads: native signing/parser, killable DNS/HTTP, bounded raw bytes.

Only the read client's before-send hook enters the child. SQL, audit, lifecycle
mutations, signing credentials and the original write client stay in the parent.
"""

from __future__ import annotations

import asyncio
import io
import json
import math
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from threading import BoundedSemaphore, Event, Lock
from time import monotonic
from typing import Any, cast

from agent_core.domain.artifact_objects import ArtifactObjectUnavailableError
from agent_core.domain.host_authority import MAX_ARTIFACT_BYTES
from botocore.awsrequest import AWSResponse  # type: ignore[import-untyped]
from botocore.client import BaseClient  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.credentials import Credentials  # type: ignore[import-untyped]
from botocore.httpsession import get_cert_path  # type: ignore[import-untyped]
from botocore.session import Session  # type: ignore[import-untyped]
from botocore.utils import get_environ_proxies  # type: ignore[import-untyped]

from agent_storage.postgres.task_io import current_task_io_deadline

_METADATA_BYTES = 65_536
_CHILDREN = BoundedSemaphore(8)
_SCOPE: ContextVar[ArtifactReadScope | None] = ContextVar("artifact_read_scope", default=None)
_BODY_LIMIT: ContextVar[int | None] = ContextVar("artifact_body_limit", default=None)
_SENT: ContextVar[bool] = ContextVar("artifact_read_sent", default=False)


def current_artifact_read_scope() -> ArtifactReadScope | None:
    return _SCOPE.get()


class ArtifactReadScope:
    def __init__(
        self, deadline: float, max_bytes: int, parent: ArtifactReadScope | None = None
    ) -> None:
        self.deadline, self.max_bytes = deadline, max_bytes
        self._cancelled: Event = parent._cancelled if parent is not None else Event()
        self._lock: Lock = parent._lock if parent is not None else Lock()
        self._children: set[subprocess.Popen[bytes]] = (
            parent._children if parent is not None else set()
        )

    def remaining(self) -> float:
        if self._cancelled.is_set():
            raise asyncio.CancelledError("immutable Artifact read cancelled")
        scoped = current_task_io_deadline()
        deadline = min(self.deadline, scoped) if scoped is not None else self.deadline
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("immutable Artifact read deadline exceeded")
        return remaining

    def cancel(self, primary: BaseException | None = None) -> None:
        self._cancelled.set()
        failure: BaseException | None = None
        with self._lock:
            for child in self._children:
                try:
                    if child.poll() is None:
                        child.kill()
                except BaseException as error:
                    if primary is not None:
                        primary.add_note(f"S3 cancel cleanup failed: {type(error).__name__}")
                    elif failure is None:
                        failure = error
        if failure is not None:
            raise failure

    def attach(self, child: subprocess.Popen[bytes]) -> None:
        with self._lock:
            self._children.add(child)
            if self._cancelled.is_set() and child.poll() is None:
                child.kill()

    def detach(self, child: subprocess.Popen[bytes]) -> None:
        with self._lock:
            self._children.discard(child)


@contextmanager
def artifact_read_scope(
    *,
    deadline: float | None = None,
    max_bytes: int = MAX_ARTIFACT_BYTES,
) -> Iterator[ArtifactReadScope]:
    active = _SCOPE.get()
    if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)):
        raise ValueError("Artifact deadline must be finite")
    if type(max_bytes) is not int or not 0 <= max_bytes <= MAX_ARTIFACT_BYTES:
        raise ValueError("Artifact byte bound is invalid")
    now = monotonic()
    deadline = min(deadline, now + 2) if deadline is not None else now + 2
    if (scoped := current_task_io_deadline()) is not None:
        deadline = min(deadline, scoped)
    if active is not None:
        deadline, max_bytes = min(deadline, active.deadline), min(max_bytes, active.max_bytes)
        if deadline == active.deadline and max_bytes == active.max_bytes:
            active.remaining()
            yield active
            active.remaining()
            return
    scope = ArtifactReadScope(deadline, max_bytes, parent=active)
    scope.remaining()
    token = _SCOPE.set(scope)
    try:
        yield scope
        scope.remaining()
    finally:
        try:
            if active is None:
                scope.cancel(sys.exc_info()[1])
        finally:
            _SCOPE.reset(token)


def bounded_s3_read_client(client: Any) -> Any:
    """Clone only native, statically credentialed clients; writes remain untouched."""
    if not isinstance(client, BaseClient):
        return client  # Deterministic injected clients retain unscoped compatibility.
    credentials = client._request_signer._credentials
    if type(credentials) is not Credentials:
        raise ValueError("bounded Artifact reads require pinned static S3 credentials")
    frozen = credentials.get_frozen_credentials()
    verify = client._endpoint.http_session._verify
    read_client = Session().create_client(
        "s3",
        endpoint_url=client.meta.endpoint_url,
        region_name=client.meta.region_name,
        aws_access_key_id=frozen.access_key,
        aws_secret_access_key=frozen.secret_key,
        aws_session_token=frozen.token,
        verify=verify,
        config=client.meta.config.merge(Config(retries={"total_max_attempts": 1})),
    )
    proxies = client.meta.config.proxies
    read_client.meta.events.register(
        "before-send.s3",
        lambda request, **_: _send(request, verify=verify, proxies=proxies),
    )
    read_client._zebra_immutable_reads = True
    return read_client


def read_s3(
    client: Any,
    operation: str,
    kwargs: Mapping[str, object],
    *,
    size: int,
    native: bool,
) -> Mapping[str, object]:
    with artifact_read_scope() as scope:
        if size < 0 or size > scope.max_bytes:
            raise ArtifactObjectUnavailableError("Artifact read exceeds its byte bound")
        if not native and current_task_io_deadline() is not None:
            raise ArtifactObjectUnavailableError("injected S3 client cannot prove bounded I/O")
        token = _BODY_LIMIT.set(size)
        sent = _SENT.set(False)
        try:
            response = getattr(client, operation)(**kwargs)
            scope.remaining()
            return cast(Mapping[str, object], response)
        finally:
            _SENT.reset(sent)
            _BODY_LIMIT.reset(token)


class _RawBody(io.BytesIO):
    def stream(self, amt: int = 65_536, **_: object) -> Iterator[bytes]:
        while chunk := self.read(amt):
            yield chunk


def _send(request: Any, *, verify: bool | str, proxies: dict[str, str] | None) -> Any:
    scope, limit = _SCOPE.get(), _BODY_LIMIT.get()
    if scope is None or limit is None or request.method not in {"HEAD", "GET"}:
        raise ArtifactObjectUnavailableError("immutable S3 read lacks its bounded scope")
    if _SENT.get():
        raise ArtifactObjectUnavailableError("immutable S3 read cannot retry or redirect")
    _SENT.set(True)
    headers = {
        key: value.decode("latin1") if isinstance(value, bytes) else str(value)
        for key, value in request.headers.items()
    }
    wire = json.dumps(
        {
            "url": request.url,
            "method": request.method,
            "headers": headers,
            "limit": limit,
            "metadata_limit": _METADATA_BYTES,
            "verify": get_cert_path(verify) if verify else False,
            "proxies": proxies if proxies is not None else get_environ_proxies(request.url),
            "timeout": scope.remaining(),
        }
    ).encode()
    if len(wire) > _METADATA_BYTES:
        raise ArtifactObjectUnavailableError("S3 request metadata exceeds its bound")
    # ponytail: eight short read children bound native blocking DNS/HTTP. Waiting
    # shares the request deadline; a future async native S3 driver can replace it.
    while not _CHILDREN.acquire(timeout=min(0.01, scope.remaining())):
        scope.remaining()
    try:
        with tempfile.TemporaryFile() as output:
            child = subprocess.Popen(
                [sys.executable, "-c", _READ_SCRIPT],
                stdin=subprocess.PIPE,
                stdout=output,
                stderr=subprocess.DEVNULL,
            )
            try:
                scope.attach(child)
                remaining = scope.remaining()
                child.communicate(wire, timeout=remaining - min(0.2, remaining * 0.1))
                scope.remaining()
                if child.returncode:
                    raise ArtifactObjectUnavailableError("bounded S3 transport failed")
                maximum = max(limit, _METADATA_BYTES) + _METADATA_BYTES + 4
                if os.fstat(output.fileno()).st_size > maximum:
                    raise ArtifactObjectUnavailableError("S3 response exceeds its bound")
                output.seek(0)
                length = int.from_bytes(output.read(4), "big")
                if not 0 < length <= _METADATA_BYTES:
                    raise ArtifactObjectUnavailableError("S3 response metadata is invalid")
                record = json.loads(output.read(length))
                body_limit = _METADATA_BYTES if record["status"] >= 300 else limit
                payload = output.read(body_limit + 1)
                if len(payload) > body_limit:
                    raise ArtifactObjectUnavailableError("S3 raw body exceeds its bound")
                scope.remaining()
                return AWSResponse(
                    request.url, record["status"], record["headers"], _RawBody(payload)
                )
            except subprocess.TimeoutExpired:
                raise TimeoutError("immutable S3 transport deadline exceeded") from None
            finally:
                primary = sys.exc_info()[1]
                failure: BaseException | None = None
                for cleanup in (
                    lambda: child.kill() if child.poll() is None else None,
                    lambda: child.stdin.close() if child.stdin is not None else None,
                    lambda: child.wait(timeout=max(0.001, scope.deadline - monotonic())),
                ):
                    try:
                        cleanup()
                    except BaseException as error:
                        if primary is not None:
                            primary.add_note(f"S3 child cleanup failed: {type(error).__name__}")
                        elif failure is None:
                            failure = error
                scope.detach(child)
                if failure is not None:
                    raise failure
    finally:
        _CHILDREN.release()


# This child uses only stdlib. Signed URL/headers arrive on stdin, never argv or
# logs. No SQL, mutation, credentials refresh, redirects, decompression or retry.
_READ_SCRIPT = """import http.client,json,ssl,sys,urllib.error,urllib.request
http.client._MAXLINE=8192
http.client._MAXHEADERS=64
data=json.load(sys.stdin)
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None
handlers=[NoRedirect(),urllib.request.ProxyHandler(data['proxies'])]
if data['url'].startswith('https:'):
    context=(ssl.create_default_context(cafile=data['verify']) if data['verify']
             else ssl._create_unverified_context())
    handlers.append(urllib.request.HTTPSHandler(context=context))
request=urllib.request.Request(data['url'],
    headers={**data['headers'],'Accept-Encoding':'identity'},method=data['method'])
try:
    response=urllib.request.build_opener(*handlers).open(request,timeout=data['timeout'])
except urllib.error.HTTPError as error:
    response=error
with response:
    status=response.status
    headers=dict(response.headers.items())
    metadata=json.dumps({'status':status,'headers':headers}).encode()
    if len(metadata)>data['metadata_limit']:
        raise ValueError('response metadata exceeds bound')
    limit=data['metadata_limit'] if status>=300 else data['limit']
    if data['method']!='HEAD' and 'Content-Length' in response.headers:
        length=int(response.headers['Content-Length'])
        if not 0<=length<=limit:
            raise ValueError('declared body exceeds bound')
    output=sys.stdout.buffer
    output.write(len(metadata).to_bytes(4,'big'))
    output.write(metadata)
    total=0
    while data['method']!='HEAD':
        chunk=response.read(min(65536,limit-total+1))
        if not chunk:
            break
        total+=len(chunk)
        if total>limit:
            raise ValueError('raw body exceeds bound')
        output.write(chunk)
    output.flush()
"""
