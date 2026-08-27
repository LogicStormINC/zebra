"""FastAPI composition root for the Host Grant broker."""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, Header, Response
from pydantic import BaseModel, Field

from zebra_host_grant_broker.config import BrokerSettings
from zebra_host_grant_broker.grant_minting import ExchangeRequest, GrantMintError, mint_grant
from zebra_host_grant_broker.keys import jwk_document, load_private_key
from zebra_host_grant_broker.trench_session import TrenchSessionError, fetch_viewer


class ExchangeBody(BaseModel):
    audience: str
    runId: str
    scopes: list[str]
    threadId: str
    resourceRefs: list[dict[str, str]] = Field(default_factory=list)


def create_app(settings: BrokerSettings) -> FastAPI:
    app = FastAPI(title="Zebra Host Grant Broker", docs_url=None, redoc_url=None)
    signing_key = load_private_key(settings.private_key_pem)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/.well-known/jwks.json")
    async def jwks() -> dict[str, object]:
        return {"keys": [jwk_document(signing_key, settings.key_id)]}

    @app.post("/exchange")
    async def exchange(
        body: ExchangeBody,
        response: Response,
        cookie: Annotated[str | None, Header()] = None,
    ) -> dict[str, str]:
        if not cookie or not cookie.strip():
            response.status_code = 401
            return {"status": "rejected", "reason": "session_cookie_missing"}
        try:
            request = ExchangeRequest.parse(body.model_dump())
            request.enforce(settings)
            viewer = fetch_viewer(
                settings.trench_me_url,
                settings.trench_sources_url,
                cookie.strip(),
                timeout_seconds=settings.trench_timeout_seconds,
            )
            request.authorize(viewer)
            grant = mint_grant(settings, signing_key, request, viewer)
        except GrantMintError as exc:
            response.status_code = 400
            return {"status": "rejected", "reason": str(exc)}
        except TrenchSessionError as exc:
            response.status_code = 401 if str(exc) == "session_inactive" else 502
            return {"status": "rejected", "reason": str(exc)}
        return {"grant": grant}

    return app
