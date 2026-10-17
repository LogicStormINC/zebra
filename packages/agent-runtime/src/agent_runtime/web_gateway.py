from __future__ import annotations

import gzip
import io
import json
import math
import os
import signal
import socket as socket  # Compatibility export for existing resolver injection.
import subprocess
import sys
import urllib.error
import urllib.request
import zlib
from collections.abc import Callable
from contextlib import redirect_stdout
from dataclasses import asdict
from http.client import HTTPException, HTTPResponse
from threading import Lock
from time import monotonic
from typing import Any

from agent_tools.web_gateway import (
    WebGatewayError,
    WebGatewayRequest,
    WebGatewayResponse,
)
from pydantic import TypeAdapter

from agent_runtime.mcp_http_egress import PublicMcpHttpsHandler
from agent_runtime.process_execution import _terminate_process_tree
from agent_runtime.public_dns import PublicAddressBlocked, public_addresses, public_host_ips
from agent_runtime.web_content import project_web_text

ALLOWED_CONTENT_TYPES = frozenset({"application/json", "application/xml", "application/xhtml+xml"})


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class LocalWebGatewayTransport:
    """Bounded local adapter; production deployments should replace it with an egress proxy."""

    def __init__(
        self,
        *,
        use_system_proxy: bool = False,
        network_cancellation_check: Callable[[], None] | None = None,
    ) -> None:
        self._use_system_proxy = use_system_proxy
        self._network_cancellation_check = network_cancellation_check

    def execute(self, request: WebGatewayRequest) -> WebGatewayResponse:
        if self._network_cancellation_check is not None:
            return TypeAdapter(WebGatewayResponse).validate_python(
                _native_network_call(
                    "fetch",
                    asdict(request),
                    self._network_cancellation_check,
                    timeout=request.timeout_seconds,
                    use_system_proxy=self._use_system_proxy,
                    max_output_bytes=max(request.max_bytes, request.max_output_bytes) * 6 + 65536,
                )
            )
        proxies = _proxy_configuration(
            request.target.hostname,
            use_system_proxy=self._use_system_proxy,
        )
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(proxies),
            _NoRedirectHandler(),
            *(() if proxies else (PublicMcpHttpsHandler(),)),
        )
        outbound = urllib.request.Request(
            request.target.url,
            headers={
                "Accept": (
                    "text/markdown, text/plain;q=0.9, text/html;q=0.9, "
                    "application/json;q=0.9, application/xml;q=0.9"
                ),
                "Accept-Encoding": "gzip",
                "User-Agent": "Zebra-Agent-Web-Gateway/1.0",
            },
            method="GET",
        )
        try:
            with opener.open(outbound, timeout=request.timeout_seconds) as response:
                content_type = _content_type(response.headers.get("Content-Type", ""))
                _require_textual_content(content_type)
                body = _read_bounded_body(response, request.max_bytes)
                charset = response.headers.get_content_charset() or "utf-8"
                text = body.decode(charset, errors="replace")
                try:
                    text, projection = project_web_text(
                        text,
                        content_type=content_type,
                        max_output_bytes=request.max_output_bytes,
                        base_url=request.target.url,
                    )
                except ValueError as exc:
                    raise WebGatewayError(str(exc), reason="content_projection_failed") from exc
                return WebGatewayResponse(
                    text=text,
                    status_code=response.status,
                    content_type=content_type,
                    byte_count=len(body),
                    metadata={
                        "transport": "local_https",
                        "redirects_followed": 0,
                        **projection,
                    },
                )
        except WebGatewayError:
            raise
        except urllib.error.HTTPError as exc:
            reason = "redirect_blocked" if 300 <= exc.code < 400 else "http_error"
            exc.close()
            raise WebGatewayError(f"web gateway HTTP error: {exc.code}", reason=reason) from exc
        except HTTPException as exc:
            raise WebGatewayError(
                "web response body is incomplete", reason="response_incomplete"
            ) from exc
        except (OSError, UnicodeError, ValueError) as exc:
            reason = (
                "private_network_blocked"
                if isinstance(getattr(exc, "reason", exc), PublicAddressBlocked)
                else "gateway_unavailable"
            )
            detail = (
                "web hostname resolves to a non-public address"
                if reason == "private_network_blocked"
                else f"web gateway request failed: {exc}"
            )
            raise WebGatewayError(detail, reason=reason) from exc


def sticky_network_cancellation_check(
    check: Callable[[], None] | None,
    *,
    reuse_doh: bool = False,
    egress_endpoint: tuple[str, int] | None = None,
) -> Callable[[], None] | None:
    """Retain the original ownership error even if a Tool catches Exception."""
    if egress_endpoint is not None and (check is None or not reuse_doh or os.name != "posix"):
        raise ValueError("controlled egress requires scoped native cancellation")
    if check is None:
        return None
    failure: BaseException | None = None
    lock = Lock()

    def require_active() -> None:
        nonlocal failure
        with lock:
            if failure is not None:
                raise failure
            try:
                check()
            except BaseException as exc:
                failure = exc
                raise

    if reuse_doh and os.name == "posix":
        from agent_runtime.native_network_scope import DohNetworkScope

        return DohNetworkScope(require_active, egress_endpoint=egress_endpoint)
    return require_active


def _native_network_call(
    operation: str,
    arguments: object,
    check: Callable[[], None],
    *,
    timeout: float,
    use_system_proxy: bool = False,
    max_output_bytes: int = 4_194_304,
    trusted_search_endpoint: str | None = None,
) -> object:
    """Kill/reap native DNS/TLS/reads, following the existing JWKS child pattern."""
    if not math.isfinite(timeout) or timeout <= 0 or max_output_bytes <= 0:
        raise ValueError("native network request bounds must be finite and positive")
    from agent_runtime.native_network_scope import DohNetworkScope

    if isinstance(check, DohNetworkScope) and operation != "browser_fetch":
        return check.call(
            operation,
            arguments,
            timeout=timeout,
            use_system_proxy=use_system_proxy,
            max_output_bytes=max_output_bytes,
            trusted_search_endpoint=trusted_search_endpoint,
        )
    check()
    deadline = monotonic() + timeout
    # ponytail: one short-lived child per native request; a persistent egress
    # driver is the throughput upgrade, not abandoning a blocked executor thread.
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from agent_runtime.web_gateway import _network_child; _network_child()",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=os.name == "posix",
    )
    try:
        data: bytes | None = json.dumps(
            (operation, arguments, use_system_proxy, max_output_bytes, trusted_search_endpoint)
        ).encode()
        while True:
            check()
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise WebGatewayError("native network request deadline exceeded")
            try:
                output, _ = child.communicate(data, timeout=min(0.05, remaining))
            except subprocess.TimeoutExpired:
                data = None
                continue
            check()  # A completed child must not publish after the Task signal.
            if child.returncode or len(output) > max_output_bytes:
                raise WebGatewayError("native network request failed or exceeded its output bound")
            result = json.loads(output)
            if "error" in result:
                raise WebGatewayError(
                    result["error"], reason=result["reason"], metadata=result.get("metadata")
                )
            return result["result"]
    except BaseException as primary:
        _cleanup_network_child(child, primary)
        raise


def _cleanup_network_child(child: subprocess.Popen[bytes], primary: BaseException) -> None:
    # Cleanup has one bounded grace period, never another body read or unbounded wait.
    cleanup_deadline = monotonic() + 0.5
    steps: tuple[tuple[str, Callable[[], object]], ...] = (
        ("group kill", lambda: _terminate_process_tree(child)),
        *(
            (("raw group kill", lambda: os.killpg(child.pid, signal.SIGKILL)),)
            if os.name == "posix"
            else ()
        ),
        ("process kill", child.kill),
        *(
            ("pipe close", pipe.close)
            for pipe in (child.stdin, child.stdout, child.stderr)
            if pipe is not None
        ),
        ("reap", lambda: child.wait(timeout=max(0.001, cleanup_deadline - monotonic()))),
    )
    for stage, action in steps:
        try:
            action()
        except ProcessLookupError:
            pass  # The child/group is already gone; continue closing and reaping.
        except BaseException as cleanup:
            primary.add_note(f"native network {stage} failed: {type(cleanup).__name__}")


def _network_child() -> None:
    """Private stdin protocol; URL admission and native transport rules are unchanged."""
    operation, arguments, proxy, maximum, search_endpoint = json.load(sys.stdin)
    result: object
    try:
        result = _execute_network_operation(operation, arguments, proxy, search_endpoint)
        output = json.dumps({"result": result})
        if len(output.encode()) > maximum:
            raise WebGatewayError(
                "native network output exceeds its byte bound", reason="response_too_large"
            )
        sys.stdout.write(output)
    except WebGatewayError as exc:
        json.dump({"error": str(exc), "reason": exc.reason, "metadata": exc.metadata}, sys.stdout)


def _execute_network_operation(
    operation: str,
    arguments: Any,
    proxy: bool,
    search_endpoint: str | None,
) -> object:
    result: object
    if operation == "fetch":
        request = TypeAdapter(WebGatewayRequest).validate_python(arguments)
        result = asdict(LocalWebGatewayTransport(use_system_proxy=proxy).execute(request))
    elif operation == "search":
        from agent_tools.web_search import WebSearchRequest

        from agent_runtime.web_search import LocalWebSearchTransport

        request_search = TypeAdapter(WebSearchRequest).validate_python(arguments)
        result = asdict(
            LocalWebSearchTransport(
                use_system_proxy=proxy, trusted_search_endpoint=search_endpoint
            ).execute(request_search)
        )
    elif operation == "search_json":
        from agent_runtime.search_providers import urllib_fetch_json

        result = urllib_fetch_json(proxy, trusted_search_endpoint=search_endpoint)(arguments)
    elif operation == "resolve":
        from agent_security.ssrf import SsrfError, resolve_and_validate

        try:
            resolve_and_validate(arguments, resolver=public_host_ips)
        except SsrfError as exc:
            raise WebGatewayError(str(exc), reason="ssrf_blocked") from exc
        result = None
    elif operation == "browser_fetch":
        from agent_tools.web_crawl import FetchProviderError, FetchRequest

        from agent_runtime.crawl_gateway import Crawl4AIFetchProvider

        browser_request = TypeAdapter(FetchRequest).validate_python(arguments["request"])
        try:
            with redirect_stdout(sys.stderr):
                result = asdict(Crawl4AIFetchProvider(arguments["headless"]).fetch(browser_request))
        except FetchProviderError as exc:
            raise WebGatewayError(str(exc), reason=exc.reason) from exc
    else:
        raise WebGatewayError("unknown native network operation")
    return result


def _read_bounded_body(response: HTTPResponse, maximum: int) -> bytes:
    """Share byte/short-body admission across fetch and both search transports."""
    content_length = response.headers.get("Content-Length")
    if content_length is not None and int(content_length) > maximum:
        raise WebGatewayError("web response exceeds the byte limit", reason="response_too_large")
    body = response.read(maximum + 1)
    if len(body) > maximum:
        raise WebGatewayError("web response exceeds the byte limit", reason="response_too_large")
    if content_length is not None and len(body) != int(content_length):
        raise WebGatewayError("web response body is incomplete", reason="response_incomplete")
    if response.headers.get("Content-Encoding", "").strip().lower() == "gzip":
        try:
            # ponytail: buffer bounded wire bytes first, then cap decoded bytes too.
            with gzip.GzipFile(fileobj=io.BytesIO(body)) as compressed:
                body = compressed.read(maximum + 1)
        except (OSError, EOFError, zlib.error) as exc:
            raise WebGatewayError(
                "compressed web response is incomplete", reason="response_incomplete"
            ) from exc
        if len(body) > maximum:
            raise WebGatewayError(
                "web response exceeds the byte limit", reason="response_too_large"
            )
    return body


def reject_non_public_resolution(hostname: str, *, port: int = 443) -> None:
    try:
        public_addresses(hostname, port)
    except PublicAddressBlocked as exc:
        raise WebGatewayError(
            "web hostname resolves to a non-public address", reason="private_network_blocked"
        ) from exc
    except OSError as exc:
        raise WebGatewayError("web hostname resolution unavailable") from exc


def _reject_non_public_resolution(hostname: str) -> None:
    # Backward-compatible alias; new callers (e.g. the MCP HTTP transport) should
    # use the parameterized public helper directly.
    reject_non_public_resolution(hostname)


def _proxy_configuration(hostname: str, *, use_system_proxy: bool) -> dict[str, str]:
    from agent_runtime.public_egress import current_public_egress

    if current_public_egress.get() is not None:
        return {}  # Explicit Cloud route never delegates target DNS to an ambient proxy.
    proxies = urllib.request.getproxies() if use_system_proxy else {}
    if proxies.get("https"):
        # ponytail: trusted-local delegates DNS and routing to the operator's HTTPS proxy;
        # direct handlers retain connection-time public-address validation.
        return proxies
    # ponytail: direct handlers validate and pin fresh DNS at connect; a separate
    # preflight repeats Fake-IP DoH without authorizing the actual socket.
    return {}


def _content_type(value: str) -> str:
    return value.partition(";")[0].strip().lower()


def _require_textual_content(content_type: str) -> None:
    if content_type.startswith("text/") or content_type in ALLOWED_CONTENT_TYPES:
        return
    raise WebGatewayError(
        f"web response content type is not textual: {content_type or 'missing'}",
        reason="unsupported_content_type",
    )
