"""Synthetic fixed-principal authority for E1 only; no production identity claims."""

import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from zebra_host_grant_broker.grant_minting import ExchangeRequest, GrantMintError

app = FastAPI(docs_url=None, redoc_url=None)
records = json.loads(Path(os.environ["E1_PRINCIPALS_FILE"]).read_text())
assert len(records) == 32
principals = {hashlib.sha256(item["token"].encode()).hexdigest(): item for item in records}
assert len(principals) == 32
NAMESPACE = os.environ.get("E1_AUTHORITY_NAMESPACE", "ha-e1-20261102")
if NAMESPACE != "ha-e1-20261102" and not re.fullmatch(r"e1-corpus-[0-9a-f]{32}", NAMESPACE):
    raise ValueError("unexpected synthetic authority namespace")
SCOPES = ("agent.run", "event.read", "artifact.read", "artifact.publish")


@app.post("/authority")
async def authority(request: Request):
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        return JSONResponse({"error": "fixture_credential_required"}, status_code=403)
    identity = principals.get(hashlib.sha256(authorization[7:].encode()).hexdigest())
    if identity is None:
        return JSONResponse({"error": "fixture_credential_invalid"}, status_code=403)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 65536:
            return JSONResponse({"error": "fixture_body_too_large"}, status_code=413)
    try:
        exchange = ExchangeRequest.parse(json.loads(body))
    except (GrantMintError, ValueError):
        return JSONResponse({"error": "fixture_request_invalid"}, status_code=422)
    if (
        exchange.audience != "zebra"
        or not set(exchange.scopes) <= set(SCOPES)
        or exchange.resource_refs
    ):
        return JSONResponse({"error": "fixture_permission_denied"}, status_code=403)
    return {
        "principalId": identity["principal"],
        "workspaceId": identity["workspace"],
        "hostAppId": "ha-e1",
        "namespaceId": NAMESPACE,
        "scopes": list(SCOPES),
        "resourceRefs": [],
        "expiresAt": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
