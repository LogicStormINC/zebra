"""Single-attempt signed admission for the isolated E1 topology."""

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_BROKER = "https://192.168.139.232:28444/exchange"
_API = "https://192.168.139.232:28443/v1/admission-operations/"
_ORIGIN = "https://ha-e1.invalid"


def _record(path: Path, body: dict) -> None:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as file:
        json.dump(body, file, separators=(",", ":"))
        file.flush()
        os.fsync(file.fileno())


async def _exchange(client: httpx.AsyncClient, token: str, binding: dict) -> str | None:
    try:
        grant = await client.post(
            _BROKER,
            json=binding,
            headers={"Authorization": "Bearer " + token},
            follow_redirects=False,
        )
        grant.raise_for_status()
        signed = grant.json()["grant"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None
    return signed if isinstance(signed, str) and signed else None


def _digest(intent: dict) -> str:
    value = {
        "task": "",
        **intent["payload"],
        "key_hash": hashlib.sha256(bytes.fromhex(intent["key"])).hexdigest(),
        "credential_hash": hashlib.sha256(b"").hexdigest(),
        "dispatch_protocol": "atomic-task-run/1",
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


async def recover_original(
    client: httpx.AsyncClient, intent: dict, *, principal_token: str
) -> tuple[int, dict, dict | None]:
    operation = str(UUID(intent["operation"]))
    digest = _digest(intent)
    signed = await _exchange(client, principal_token, intent["binding"])
    if signed is None:
        raise RuntimeError("original receipt grant unavailable")
    response = await client.get(
        _API + operation,
        headers={
            "Authorization": "Bearer " + signed,
            "Origin": _ORIGIN,
            "X-Zebra-Admission-Key": intent["key"],
            "X-Zebra-Admission-Hash": digest,
        },
        follow_redirects=False,
    )
    receipt = response.json()
    if response.status_code != 200 or receipt.get("status") != "completed":
        return response.status_code, receipt, None
    if receipt.get("operation") != operation or receipt.get("request_hash") != digest:
        raise ValueError("returned receipt does not match the original operation")
    sealed = base64.b64decode(receipt["sealed_response"], validate=True)
    original = json.loads(
        AESGCM(bytes.fromhex(intent["key"])).decrypt(sealed[:12], sealed[12:], digest.encode())
    )
    return response.status_code, receipt, original


async def submit_once(
    client: httpx.AsyncClient,
    evidence: Path,
    *,
    index: int,
    principal_token: str,
    task: dict,
) -> str:
    binding = {
        "audience": "zebra",
        "threadId": str(uuid4()),
        "runId": str(uuid4()),
        "scopes": ["agent.run", "event.read", "artifact.read", "artifact.publish"],
    }
    operation = str(uuid4())
    key = os.urandom(32).hex()
    payload = {"kind": "task_create", "run": binding["runId"], "payload": task}
    signed = await _exchange(client, principal_token, binding)
    if signed is None:
        return "grant_failed"

    intent = {"operation": operation, "key": key, "binding": binding, "payload": payload}
    _record(evidence / f"{index}.intent.json", intent)
    try:
        response = await client.post(
            _API + operation,
            json=payload,
            follow_redirects=False,
            headers={
                "Authorization": "Bearer " + signed,
                "Origin": _ORIGIN,
                "X-Zebra-Admission-Key": key,
                "X-Zebra-Admission-Protocol": "atomic-task-run/1",
            },
        )
        receipt = response.json()
    except (httpx.HTTPError, ValueError):
        return "outcome_unknown"
    _record(
        evidence / f"{index}.response.json",
        {"status_code": response.status_code, "receipt": receipt},
    )
    if (
        response.status_code == 200
        and isinstance(receipt, dict)
        and receipt.get("response_status") == 201
        and receipt.get("status") == "completed"
        and receipt.get("sealed_response")
    ):
        return "accepted"
    return "response_requires_classification"


async def _check() -> None:
    from tempfile import TemporaryDirectory

    from open_loop import run_offers

    with TemporaryDirectory() as folder:
        evidence = Path(folder)
        posts = []

        async def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == _BROKER:
                return httpx.Response(200, json={"grant": "test-grant"})
            if request.method == "GET":
                assert request.url.path.endswith(intent["operation"])
                digest = _digest(intent)
                assert request.headers["X-Zebra-Admission-Hash"] == digest
                nonce = os.urandom(12)
                sealed = AESGCM(bytes.fromhex(intent["key"])).encrypt(
                    nonce, b'{"task_id":"original"}', digest.encode()
                )
                return httpx.Response(
                    200,
                    json={
                        "status": "completed",
                        "operation": intent["operation"],
                        "request_hash": digest,
                        "sealed_response": base64.b64encode(nonce + sealed).decode(),
                    },
                )
            posts.append(request.url.path)
            assert len(list(evidence.glob("*.intent.json"))) == len(posts)
            raise httpx.ReadError("lost response")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:

            async def submit(index: int) -> str:
                return await submit_once(
                    client, evidence, index=index, principal_token="test-principal", task={}
                )

            offers = await run_offers(
                submit, rate=10, duration=0.2, max_inflight=2, request_timeout=1
            )
            intent = json.loads((evidence / "0.intent.json").read_text())
            status, _, original = await recover_original(
                client, intent, principal_token="test-principal"
            )
            assert status == 200 and original == {"task_id": "original"}
        assert len(posts) == len(set(posts)) == 2
        assert all(offer.disposition == "outcome_unknown" for offer in offers)
        assert not list(evidence.glob("*.response.json"))


if __name__ == "__main__":
    asyncio.run(_check())
