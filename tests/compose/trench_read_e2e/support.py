"""Small, secret-free transport helpers for the Trench E2E runner."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


class E2EError(RuntimeError):
    """A bounded, secret-free runner failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ConfigError(E2EError):
    def __init__(self, missing: list[str], invalid: list[str]):
        self.missing = missing
        self.invalid = invalid
        super().__init__("missing_environment" if missing else "invalid_environment")


@dataclass(frozen=True, slots=True)
class Config:
    bff_url: str
    read_tools_url: str
    session_cookie: str
    event_id: str
    trench_health_url: str
    trench_database_dsn: str
    trench_redis_url: str
    trench_object_store_url: str
    trench_snapshot_url: str
    zebra_base_url: str
    zebra_health_url: str
    zebra_database_dsn: str
    zebra_redis_url: str
    zebra_object_store_url: str
    grant_exchange_url: str
    worker_restart_url: str
    request_id: str
    timeout_seconds: int
    operator_token: str | None

    @property
    def command_url(self) -> str:
        return join_url(self.zebra_base_url, "/agui/commands")

    @property
    def task_url(self) -> str:
        return join_url(self.zebra_base_url, "/tasks")


@dataclass(frozen=True, slots=True)
class HttpResult:
    status: int
    body: bytes
    headers: Mapping[str, str]

    def json(self) -> object:
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise E2EError("invalid_json") from exc


@dataclass(frozen=True, slots=True)
class SseEvent:
    cursor: str | None
    data: Mapping[str, object]


HOST_GRANT_SCOPES = (
    "agent.run",
    "event.read",
    "evidence.read",
    "entity.read",
    "topic.read",
)


def missing_environment(environment: Mapping[str, str], required: tuple[str, ...]) -> list[str]:
    return [name for name in required if not environment.get(name, "").strip()]


def load_config(environment: Mapping[str, str], required: tuple[str, ...]) -> Config:
    missing = missing_environment(environment, required)
    invalid: list[str] = []
    for name in required:
        value = environment.get(name, "").strip()
        if value and name.endswith(("_URL", "_HEALTH_URL")):
            try:
                validate_endpoint(value)
            except E2EError:
                invalid.append(name)
    timeout_text = environment.get("ZEBRA_E2E_TIMEOUT_SECONDS", "60").strip()
    try:
        timeout = int(timeout_text)
    except ValueError:
        timeout = 0
    if timeout < 5 or timeout > 300:
        invalid.append("ZEBRA_E2E_TIMEOUT_SECONDS")
    cookie = environment.get("TRENCH_E2E_SESSION_COOKIE", "").strip()
    request_id = environment.get("TRENCH_E2E_REQUEST_ID", f"trench-e2e-{uuid.uuid4()}").strip()
    if cookie and (len(cookie) > 8192 or any(char in cookie for char in "\r\n")):
        invalid.append("TRENCH_E2E_SESSION_COOKIE")
    if len(request_id) > 128 or any(char in request_id for char in "\r\n"):
        invalid.append("TRENCH_E2E_REQUEST_ID")
    if missing or invalid:
        raise ConfigError(missing, invalid)
    return Config(
        bff_url=validate_endpoint(environment["TRENCH_E2E_BFF_URL"]),
        read_tools_url=validate_endpoint(environment["TRENCH_E2E_READ_TOOLS_URL"]),
        session_cookie=cookie,
        event_id=environment["TRENCH_E2E_EVENT_ID"].strip(),
        trench_health_url=validate_endpoint(environment["TRENCH_E2E_HEALTH_URL"]),
        trench_database_dsn=environment["TRENCH_E2E_DATABASE_DSN"].strip(),
        trench_redis_url=environment["TRENCH_E2E_REDIS_URL"].strip(),
        trench_object_store_url=validate_endpoint(
            environment["TRENCH_E2E_OBJECT_STORE_HEALTH_URL"]
        ),
        trench_snapshot_url=validate_endpoint(environment["TRENCH_E2E_BUSINESS_SNAPSHOT_URL"]),
        zebra_base_url=validate_endpoint(environment["ZEBRA_E2E_BASE_URL"]),
        zebra_health_url=validate_endpoint(environment["ZEBRA_E2E_HEALTH_URL"]),
        zebra_database_dsn=environment["ZEBRA_E2E_DATABASE_DSN"].strip(),
        zebra_redis_url=environment["ZEBRA_E2E_REDIS_URL"].strip(),
        zebra_object_store_url=validate_endpoint(environment["ZEBRA_E2E_OBJECT_STORE_HEALTH_URL"]),
        grant_exchange_url=validate_endpoint(environment["ZEBRA_E2E_GRANT_EXCHANGE_URL"]),
        worker_restart_url=validate_endpoint(environment["ZEBRA_E2E_WORKER_RESTART_URL"]),
        request_id=request_id,
        timeout_seconds=timeout,
        operator_token=environment.get("ZEBRA_E2E_OPERATOR_TOKEN", "").strip() or None,
    )


def validate_endpoint(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise E2EError("invalid_endpoint")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise E2EError("invalid_endpoint")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def join_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def cookie_headers(config: Config) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Cookie": config.session_cookie,
        "X-Trench-Request-Id": config.request_id,
    }


def request(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    payload: Mapping[str, object] | None = None,
    timeout: int = 30,
) -> HttpResult:
    body = None
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request_obj = Request(url, data=body, headers=request_headers, method=method.upper())
    try:
        with urlopen(request_obj, timeout=timeout) as response:
            return HttpResult(
                response.status,
                response.read(1_048_576),
                {key.lower(): value for key, value in response.headers.items()},
            )
    except HTTPError as error:
        return HttpResult(
            error.code,
            error.read(1_048_576),
            {key.lower(): value for key, value in error.headers.items()},
        )
    except (TimeoutError, OSError, URLError) as exc:
        raise E2EError("network_unavailable") from exc


def require_status(response: HttpResult, allowed: set[int]) -> None:
    if response.status not in allowed:
        raise E2EError(f"http_{response.status}")


def json_object(response: HttpResult) -> dict[str, object]:
    payload = response.json()
    if not isinstance(payload, dict):
        raise E2EError("invalid_json_object")
    return payload


def health(url: str, timeout: int) -> None:
    response = request("GET", url, headers={"Accept": "application/json"}, timeout=timeout)
    require_status(response, set(range(200, 300)))


def postgres_probe(dsn: str) -> None:
    try:
        import psycopg
    except ImportError as exc:
        raise E2EError("psycopg_unavailable") from exc
    try:
        with psycopg.connect(dsn, connect_timeout=5, autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                if cursor.fetchone() != (1,):
                    raise E2EError("postgres_probe_failed")
    except E2EError:
        raise
    except Exception as exc:
        raise E2EError("postgres_unavailable") from exc


def redis_probe(url: str) -> None:
    try:
        import redis
    except ImportError as exc:
        raise E2EError("redis_unavailable") from exc
    client = redis.Redis.from_url(url, socket_connect_timeout=5, socket_timeout=5)
    try:
        if not client.ping():
            raise E2EError("redis_probe_failed")
    except E2EError:
        raise
    except Exception as exc:
        raise E2EError("redis_unavailable") from exc
    finally:
        client.close()


def business_snapshot(config: Config) -> str:
    response = request(
        "GET",
        config.trench_snapshot_url,
        headers=cookie_headers(config),
        timeout=config.timeout_seconds,
    )
    require_status(response, {200})
    payload = json_object(response)
    tables = payload.get("tables")
    if not isinstance(tables, dict) or not tables:
        raise E2EError("invalid_business_snapshot")
    canonical = json.dumps(tables, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def read_manifest_and_event(config: Config, expected_tools: set[str]) -> None:
    response = request(
        "GET",
        join_url(config.read_tools_url, "/manifest"),
        headers=cookie_headers(config),
        timeout=config.timeout_seconds,
    )
    require_status(response, {200})
    manifest = json_object(response)
    tools = manifest.get("tools")
    if not isinstance(tools, list):
        raise E2EError("read_manifest_mismatch")
    names = {item.get("name") for item in tools if isinstance(item, dict)}
    if names != expected_tools or manifest.get("manifestVersion") != "trench-native-v2":
        raise E2EError("read_manifest_mismatch")
    invoke = request(
        "POST",
        join_url(config.read_tools_url, "/tools/events.get_event/invoke"),
        headers={**cookie_headers(config), "X-Zebra-Workload-Identity": "trench-read-only"},
        payload={"toolName": "events.get_event", "arguments": {"event_id": config.event_id}},
        timeout=config.timeout_seconds,
    )
    require_status(invoke, {200})
    result = json_object(invoke)
    metadata = result.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("read_only") is not True:
        raise E2EError("read_tool_not_read_only")
    output = result.get("output")
    if not isinstance(output, str):
        raise E2EError("read_tool_output_invalid")
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        raise E2EError("read_tool_output_invalid") from exc
    if not isinstance(parsed, dict) or parsed.get("tool") != "events.get_event":
        raise E2EError("read_tool_output_mismatch")


def bootstrap(config: Config) -> str:
    response = request(
        "POST",
        join_url(config.bff_url, "/api/copilotkit-zebra/bootstrap"),
        headers={**cookie_headers(config), "Content-Type": "application/json"},
        payload={"eventId": config.event_id},
        timeout=config.timeout_seconds,
    )
    require_status(response, {200})
    task_id = json_object(response).get("taskId")
    if not isinstance(task_id, str) or not task_id:
        raise E2EError("bootstrap_invalid")
    return task_id


def obtain_grant(config: Config, thread_id: str, run_id: str) -> str:
    response = request(
        "POST",
        config.grant_exchange_url,
        headers={**cookie_headers(config), "Content-Type": "application/json"},
        payload={
            "audience": "zebra",
            "scopes": list(HOST_GRANT_SCOPES),
            "threadId": thread_id,
            "runId": run_id,
        },
        timeout=config.timeout_seconds,
    )
    require_status(response, set(range(200, 300)))
    payload = json_object(response)
    grant = payload.get("grant") or payload.get("token")
    if not isinstance(grant, str) or not grant.strip():
        raise E2EError("grant_exchange_invalid")
    return grant.strip()


def task_state(config: Config, task_id: str, run_id: str) -> int:
    grant = obtain_grant(config, task_id, run_id)
    response = request(
        "GET",
        f"{config.task_url}/{quote(task_id, safe='')}",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {grant}",
            "X-Trench-Request-Id": config.request_id,
        },
        timeout=config.timeout_seconds,
    )
    require_status(response, {200})
    revision = json_object(response).get("current_sequence")
    if not isinstance(revision, int) or revision < 0:
        raise E2EError("task_revision_invalid")
    return revision


def run_input(task_id: str, run_id: str, prompt: str, expected_revision: int) -> dict[str, object]:
    return {
        "threadId": task_id,
        "runId": run_id,
        "state": {},
        "messages": [{"id": str(uuid.uuid4()), "role": "user", "content": prompt}],
        "tools": [],
        "context": [],
        "forwardedProps": {"expectedRevision": expected_revision},
    }


def sse_events(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str],
    payload: Mapping[str, object] | None,
    timeout: int,
    stop_after: int | None = None,
    cursor: str | None = None,
) -> list[SseEvent]:
    query_url = f"{url}?{urlencode({'cursor': cursor})}" if cursor else url
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request_headers = dict(headers)
    if payload is not None:
        request_headers.setdefault("Content-Type", "application/json")
    request_obj = Request(query_url, data=body, headers=request_headers, method=method.upper())
    events: list[SseEvent] = []
    current_id: str | None = None
    data_lines: list[str] = []
    deadline = time.monotonic() + timeout
    try:
        with urlopen(request_obj, timeout=timeout) as response:
            content_type = response.headers.get("content-type", "")
            if response.status != 200 or "text/event-stream" not in content_type:
                raise E2EError("stream_rejected")
            while time.monotonic() < deadline:
                line = response.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="strict").rstrip("\r\n")
                if not decoded:
                    event = decode_sse(current_id, data_lines)
                    if event is not None:
                        events.append(event)
                        if stop_after is not None and len(events) >= stop_after:
                            return events
                    current_id, data_lines = None, []
                    continue
                if decoded.startswith("id:"):
                    current_id = decoded[3:].strip()
                elif decoded.startswith("data:"):
                    data_lines.append(decoded[5:].lstrip())
            if not events:
                raise E2EError("stream_timeout")
    except HTTPError as error:
        raise E2EError(f"stream_http_{error.code}") from error
    except (TimeoutError, OSError, URLError) as exc:
        raise E2EError("stream_unavailable") from exc
    return events


def decode_sse(cursor: str | None, data_lines: list[str]) -> SseEvent | None:
    if not data_lines:
        return None
    try:
        payload = json.loads("\n".join(data_lines))
    except json.JSONDecodeError as exc:
        raise E2EError("stream_invalid_event") from exc
    if not isinstance(payload, dict):
        raise E2EError("stream_invalid_event")
    return SseEvent(cursor, payload)
