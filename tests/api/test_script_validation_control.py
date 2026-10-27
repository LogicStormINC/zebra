"""Current authority, retained work slots, cancellation and bounded streaming."""

import asyncio
import threading

import httpx
import pytest
from zebra_agent_api import script_validation as module
from zebra_agent_api.script_validation_contract import (
    CONTRACT_PATH as GET,
)
from zebra_agent_api.script_validation_contract import (
    VALIDATION_PATH as POST,
)
from zebra_agent_api.script_validation_contract import (
    ScriptValidationRequest,
)

from tests.api.test_bundle_management import write
from tests.api.test_script_validation import configured_fixture, isolated_app


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_final_full_authority_recheck(tmp_path, monkeypatch, method):
    active, path, approval, request, headers = configured_fixture(tmp_path)
    original_contract = module.native_script_validation_contract
    original_script = ScriptValidationRequest.script
    changes = [
        {"credential_sha256": "0" * 64},
        {"trust_revision": 2},
        {"actions": ["script.validate"] if method == "GET" else ["script.contract.read"]},
        {"expires_at": "2000-01-01T00:00:00Z"},
        {"expires_at": "2098-01-01T00:00:00Z"},
        {"actions": list(reversed(approval["actions"]))},
        {"scope": {**approval["scope"], "target_id": "other-target"}},
        {"scope": {**approval["scope"], "authority_issuer": "https://other.example"}},
    ]
    for change in changes:
        write(path, approval)
        entered, release = threading.Event(), threading.Event()

        def block_contract(entered=entered, release=release):
            entered.set()
            assert release.wait(4)
            return original_contract()

        def block_script(self, entered=entered, release=release):
            entered.set()
            assert release.wait(4)
            return original_script(self)

        monkeypatch.setattr(
            module,
            "native_script_validation_contract",
            block_contract if method == "GET" else original_contract,
        )
        monkeypatch.setattr(
            ScriptValidationRequest, "script", block_script if method == "POST" else original_script
        )

        async def check(change=change, entered=entered, release=release):
            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=isolated_app(active)),
                    base_url="https://owned",
                ) as client:
                    task = asyncio.create_task(
                        client.get(GET, headers=headers)
                        if method == "GET"
                        else client.post(POST, headers=headers, json=request)
                    )
                    async with asyncio.timeout(3):
                        while not entered.is_set():
                            await asyncio.sleep(0.001)
                    write(path, {**approval, **change})
                    release.set()
                    response = await task
                    assert response.status_code in (401, 403), response.text
                    assert response.headers["cache-control"] == "no-store"
            finally:
                release.set()

        asyncio.run(check())


@pytest.mark.parametrize("cancel", [False, True])
def test_late_work_keeps_eight_slots_and_errors_are_consumed(tmp_path, monkeypatch, cancel):
    active, _, _, request, headers = configured_fixture(tmp_path)
    entered = []
    release = threading.Event()
    original = module.load_script_validation_approval

    def blocked(*args):
        entered.append(1)
        assert release.wait(5)
        raise ValueError("DO_NOT_ECHO_LATE_FAILURE")

    monkeypatch.setattr(module, "load_script_validation_approval", blocked)
    monkeypatch.setattr(module, "REQUEST_TIMEOUT", 4 if cancel else 0.04)
    app = isolated_app(active)

    async def check():
        errors = []
        asyncio.get_running_loop().set_exception_handler(lambda _loop, value: errors.append(value))
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://owned"
            ) as client:
                tasks = [
                    asyncio.create_task(
                        client.get(GET, headers=headers)
                        if n % 2
                        else client.post(POST, headers=headers, json=request)
                    )
                    for n in range(8)
                ]
                async with asyncio.timeout(3):
                    while len(entered) != 8:
                        await asyncio.sleep(0.001)
                if cancel:
                    for task in tasks:
                        task.cancel()
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    assert all(isinstance(item, asyncio.CancelledError) for item in results)
                else:
                    responses = await asyncio.gather(*tasks)
                    assert all(item.status_code == 503 for item in responses)
                    assert all("DO_NOT_ECHO" not in item.text for item in responses)
                for route in (GET, POST):
                    response = await client.request(
                        "GET" if route == GET else "POST",
                        route,
                        headers=headers,
                        json=None if route == GET else request,
                    )
                    assert response.status_code == 429 and response.headers["retry-after"] == "1"
                monkeypatch.setattr(module, "load_script_validation_approval", original)
                release.set()
                async with asyncio.timeout(3):
                    while (await client.get(GET, headers=headers)).status_code == 429:
                        await asyncio.sleep(0.001)
                assert (await client.get(GET, headers=headers)).status_code == 200
                assert errors == []
        finally:
            release.set()

    asyncio.run(check())


def test_stream_deadline_and_actual_stream_limit(tmp_path, monkeypatch):
    active, _, _, _, headers = configured_fixture(tmp_path)
    monkeypatch.setattr(module, "BODY_TIMEOUT", 0.02)
    app = isolated_app(active)
    streamed = 0

    async def slow():
        yield b"{"
        await asyncio.sleep(2)
        yield b"}"

    async def large():
        nonlocal streamed
        for _ in range(80):
            streamed += 1
            yield b" " * 1024

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://owned"
        ) as client:
            post_headers = {**headers, "Content-Type": "application/json"}
            assert (
                await client.post(POST, headers=post_headers, content=slow())
            ).status_code == 400
            assert (
                await client.post(POST, headers=post_headers, content=large())
            ).status_code == 400
            assert streamed == 65  # Stops reading at the first oversized chunk.
            assert (await client.get(GET, headers=headers)).status_code == 200

    asyncio.run(check())
