"""Single-attempt signed admission for the isolated E1 topology."""

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx

_BROKER = "https://192.168.139.232:28444/exchange"
_API = "https://192.168.139.232:28443/v1/admission-operations/"
_ORIGIN = "https://ha-e1.invalid"


def _record(path: Path, body: dict) -> None:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as file:
        json.dump(body, file, separators=(",", ":"))
        file.flush()
        os.fsync(file.fileno())


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
    try:
        grant = await client.post(
            _BROKER,
            json=binding,
            headers={"Authorization": "Bearer " + principal_token},
            follow_redirects=False,
        )
        grant.raise_for_status()
        signed = grant.json()["grant"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return "grant_failed"
    if not isinstance(signed, str) or not signed:
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
        assert len(posts) == len(set(posts)) == 2
        assert all(offer.disposition == "outcome_unknown" for offer in offers)
        assert not list(evidence.glob("*.response.json"))


if __name__ == "__main__":
    asyncio.run(_check())
