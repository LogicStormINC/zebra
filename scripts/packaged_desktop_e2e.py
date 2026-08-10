#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

API_URL = "http://127.0.0.1:18080"
DRIVER_URL = "http://127.0.0.1:4444"
AUTH_HEADERS = {"Authorization": "Bearer e2e-token"}


def request_json(
    method: str,
    url: str,
    payload: object | None = None,
    headers: dict[str, str] | None = None,
    *,
    timeout: float = 10,
) -> dict[str, Any]:
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            decoded = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise AssertionError(
            f"{method} {url} returned HTTP {exc.code}: {detail}"
        ) from exc
    if not isinstance(decoded, dict):
        raise TypeError("WebDriver response must be a JSON object")
    return decoded


def wait_for_api() -> dict[str, Any]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            return request_json("GET", f"{API_URL}/health")
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    raise AssertionError("API did not become ready")


def wait_for_session(
    session_id: str,
    predicate: Callable[[dict[str, Any]], bool],
    *,
    timeout: float = 40,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    session: dict[str, Any] = {}
    while time.monotonic() < deadline:
        session = request_json("GET", f"{API_URL}/tasks/{session_id}", headers=AUTH_HEADERS)
        if predicate(session):
            return session
        time.sleep(0.25)
    raise AssertionError(f"session {session_id} did not reach the expected state: {session!r}")


def wait_for_stream_event(session_id: str, event_type: str, *, timeout: float = 40) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        request = urllib.request.Request(
            f"{API_URL}/tasks/{session_id}/stream",
            headers=AUTH_HEADERS,
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                text = str(response.read().decode())
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
            continue
        if f'"event_type": "{event_type}"' in text:
            return text
        time.sleep(0.25)
    raise AssertionError(f"session stream did not contain {event_type!r}")


class PackagedApp:
    def __init__(self, application: Path) -> None:
        self.driver = subprocess.Popen(("tauri-driver",), start_new_session=True)
        self.session_id = self._create_session(application)

    def _create_session(self, application: Path) -> str:
        deadline = time.monotonic() + 30
        payload = {
            "capabilities": {
                "alwaysMatch": {
                    "browserName": "wry",
                    "tauri:options": {"application": str(application.resolve())},
                }
            }
        }
        while time.monotonic() < deadline:
            try:
                response = request_json(
                    "POST", f"{DRIVER_URL}/session", payload, timeout=120
                )
                value = response.get("value", response)
                session_id = value.get("sessionId") or response.get("sessionId")
                if isinstance(session_id, str):
                    return session_id
            except (OSError, urllib.error.URLError):
                time.sleep(0.25)
        raise AssertionError("tauri-driver did not launch the packaged application")

    def execute(self, script: str, *arguments: object) -> Any:
        response = request_json(
            "POST",
            f"{DRIVER_URL}/session/{self.session_id}/execute/sync",
            {"script": script, "args": list(arguments)},
        )
        return response.get("value")

    def body(self) -> str:
        return self.element_text("css selector", "body")

    def element_text(self, using: str, selector: str) -> str:
        for attempt in range(5):
            element_id = self._element(using, selector)
            try:
                response = request_json(
                    "GET",
                    f"{DRIVER_URL}/session/{self.session_id}/element/{element_id}/text",
                )
            except AssertionError as exc:
                if "stale element reference" in str(exc) and attempt < 4:
                    continue
                raise
            except OSError:
                if attempt < 4:
                    continue
                raise
            value = response.get("value")
            if not isinstance(value, str):
                raise AssertionError(f"WebDriver element {selector!r} text is unavailable")
            return value
        raise AssertionError(f"WebDriver element {selector!r} remained stale")

    def wait_body(self, expected: str, *, timeout: float = 30) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            body = self.body()
            if expected in body:
                return body
            time.sleep(0.25)
        raise AssertionError(f"packaged UI did not show {expected!r}; body={self.body()!r}")

    def wait_element(self, using: str, selector: str, *, timeout: float = 30) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                return self._element(using, selector)
            except AssertionError:
                pass
            time.sleep(0.25)
        raise AssertionError(f"packaged UI element {selector!r} did not appear")

    def _element(self, using: str, value: str) -> str:
        for attempt in range(5):
            try:
                response = request_json(
                    "POST",
                    f"{DRIVER_URL}/session/{self.session_id}/element",
                    {"using": using, "value": value},
                )
                break
            except OSError:
                if attempt == 4:
                    raise
                time.sleep(0.25)
        element = response.get("value")
        if not isinstance(element, dict):
            raise AssertionError(f"WebDriver element {value!r} is unavailable")
        element_id = element.get("element-6066-11e4-a52e-4f735466cecf")
        if not isinstance(element_id, str):
            raise AssertionError(f"WebDriver element {value!r} has no id")
        return element_id

    def click(self, using: str, value: str) -> None:
        element_id = self._element(using, value)
        request_json(
            "POST",
            f"{DRIVER_URL}/session/{self.session_id}/element/{element_id}/click",
            {},
        )

    def click_text(self, text: str) -> None:
        self.click("xpath", f"//button[normalize-space(.)='{text}']")

    def click_aria(self, label: str) -> None:
        self.click("css selector", f'[aria-label="{label}"]')

    def submit(self, prompt: str) -> None:
        selector = 'textarea[name="task-prompt"]'
        for attempt in range(5):
            element_id = self._element("css selector", selector)
            try:
                request_json(
                    "POST",
                    f"{DRIVER_URL}/session/{self.session_id}/element/{element_id}/clear",
                    {},
                )
                request_json(
                    "POST",
                    f"{DRIVER_URL}/session/{self.session_id}/element/{element_id}/value",
                    {"text": prompt, "value": list(prompt)},
                )
            except OSError:
                pass
            try:
                response = request_json(
                    "GET",
                    f"{DRIVER_URL}/session/{self.session_id}/element/{element_id}/property/value",
                )
                if response.get("value") == prompt:
                    break
            except OSError:
                pass
            if attempt == 4:
                raise AssertionError(f"WebDriver did not set prompt {prompt!r}")
            time.sleep(0.25)
        self.click_aria("发送任务")

    def configure(self, workspace: Path) -> None:
        self.execute(
            """
            localStorage.clear();
            localStorage.setItem('zebra-agent-desktop.operator-config', JSON.stringify({
              apiBaseUrl: arguments[0], authToken: 'e2e-token', sessionId: '',
              userId: '', tenantId: ''
            }));
            localStorage.setItem('zebra-agent-desktop.task-launch-config', JSON.stringify({
              workspace: arguments[1], policyProfile: 'workspace_write',
              toolProfile: 'coding', networkProfile: 'none', networkAllowlist: [],
              mcpAllowlist: [], mcpResourceIds: [], mcpPromptId: null,
              mcpPromptArguments: {}, mcpPromptSchema: null
            }));
            location.reload();
            """,
            API_URL,
            str(workspace),
        )

    def active_session_id(self) -> str:
        return str(
            self.execute(
                """
                const raw = localStorage.getItem('zebra-agent-desktop.operator-config');
                return raw ? JSON.parse(raw).sessionId ?? '' : '';
                """
            )
        )

    def wait_active_session_id(self, *, timeout: float = 30) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            session_id = self.active_session_id()
            if session_id:
                return session_id
            time.sleep(0.25)
        raise AssertionError("packaged UI did not persist the active session id")

    def screenshot(self, path: Path) -> None:
        response = request_json(
            "GET", f"{DRIVER_URL}/session/{self.session_id}/screenshot"
        )
        path.write_bytes(base64.b64decode(response["value"]))

    def refresh(self) -> None:
        request_json(
            "POST", f"{DRIVER_URL}/session/{self.session_id}/refresh", {}
        )

    def close(self) -> None:
        try:
            request_json("DELETE", f"{DRIVER_URL}/session/{self.session_id}")
        finally:
            stop_process(self.driver)


def start_api(repository: Path, database: Path) -> subprocess.Popen[bytes]:
    environment = {
        **os.environ,
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
        "ZEBRA_API_AUTH_TOKEN": "e2e-token",
        "ZEBRA_DATABASE_URL": str(database),
        "ZEBRA_E2E_API_KEY": "e2e-secret",
        "ZEBRA_MODEL_API_KEY_ENV": "ZEBRA_E2E_API_KEY",
        "ZEBRA_MODEL_BASE_URL": "http://127.0.0.1:14010",
        "ZEBRA_MODEL_MAX_RETRIES": "0",
        "ZEBRA_MODEL_NAME": "e2e-stream",
        "ZEBRA_MODEL_PROVIDER": "openai",
        "ZEBRA_PROFILE": "local",
        "ZEBRA_RUNTIME_CLASS": "os-sandbox",
    }
    return subprocess.Popen(
        (
            "uv",
            "run",
            "--all-packages",
            "uvicorn",
            "zebra_agent_api.http:create_http_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            "18080",
        ),
        cwd=repository,
        env=environment,
        start_new_session=True,
    )


def stop_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run(application: Path, evidence_path: Path, screenshot_path: Path) -> None:
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = "127.0.0.1,localhost"
    repository = Path(__file__).resolve().parents[1]
    desktop = repository / "UI" / "desktop"
    temporary = Path(tempfile.mkdtemp(prefix="zebra-packaged-e2e-"))
    workspace = temporary / "workspace"
    workspace.mkdir()
    database = temporary / "sessions.sqlite"
    provider = subprocess.Popen(
        ("node", "e2e/support/mock-provider.mjs"),
        cwd=desktop,
        start_new_session=True,
    )
    api = start_api(repository, database)
    app: PackagedApp | None = None
    steps: list[str] = []
    try:
        health = wait_for_api()
        assert health["runtime"] == {
            "profile": "local",
            "runtime_class": "os-sandbox",
            "fallback_allowed": False,
        }
        app = PackagedApp(application)
        app.configure(workspace)
        app.wait_body("本地运行时已连接")
        steps.append("runtime-profile-no-fallback")

        app.submit("E2E_STOP_STREAM packaged cancellation")
        stop_session_id = app.wait_active_session_id()
        wait_for_session(
            stop_session_id,
            lambda session: int(session.get("current_sequence", 0)) >= 4,
        )
        app.click_aria("停止任务")
        wait_for_session(stop_session_id, lambda session: session.get("status") == "cancelled")
        app.wait_body("已停止")
        stop_events = wait_for_stream_event(stop_session_id, "session_cancelled")
        assert '"event_type": "session_completed"' not in stop_events
        steps.append("cancellation")

        app.submit("E2E_APPROVAL packaged approval")
        app.wait_body("Agent 需要人工确认", timeout=40)
        app.wait_body("command.run")
        app.click_text("批准")
        app.wait_body("APPROVAL_COMPLETE", timeout=40)
        session_id = app.wait_active_session_id()
        session = request_json(
            "GET", f"{API_URL}/tasks/{session_id}", headers=AUTH_HEADERS
        )
        assert session["workspace"]["runtime_name"] == "os-sandbox"
        app.refresh()
        app.wait_body("Runtime")
        app.wait_element(
            "css selector",
            '[data-testid="runtime-name"][data-runtime-name="os-sandbox"]',
        )
        steps.append("approval-real-runtime")

        app.submit("E2E_FAILURE packaged failure")
        app.wait_body("任务已暂停", timeout=40)
        app.wait_body("已暂停")
        failure_session_id = app.wait_active_session_id()
        failure_session = request_json(
            "GET", f"{API_URL}/tasks/{failure_session_id}", headers=AUTH_HEADERS
        )
        assert failure_session["status"] == "suspended"
        steps.append("failure-visible")

        stop_process(api)
        app.wait_body("本地运行时未连接", timeout=15)
        api = start_api(repository, database)
        wait_for_api()
        app.refresh()
        app.wait_body("本地运行时已连接", timeout=20)
        app.wait_body("E2E_FAILURE packaged failure", timeout=20)
        app.wait_body("任务已暂停")
        recovered_session = request_json(
            "GET", f"{API_URL}/tasks/{failure_session_id}", headers=AUTH_HEADERS
        )
        assert recovered_session["status"] == "suspended"
        steps.append("restart-durable-recovery")

        app.screenshot(screenshot_path)
        evidence_path.write_text(
            json.dumps(
                {
                    "application": str(application),
                    "runtime": health["runtime"],
                    "steps": steps,
                    "session_id": app.active_session_id(),
                    "passed": True,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    finally:
        if app is not None:
            app.close()
        stop_process(api)
        stop_process(provider)
        shutil.rmtree(temporary, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--application", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--screenshot", type=Path, required=True)
    arguments = parser.parse_args()
    run(arguments.application, arguments.evidence, arguments.screenshot)


if __name__ == "__main__":
    main()
