"""FastAPI composition root for the Host Grant broker."""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, Header, Request, Response

from zebra_host_grant_broker.config import BrokerSettings
from zebra_host_grant_broker.current_authority import AuthorityError, fetch_authority
from zebra_host_grant_broker.grant_minting import (
    ExchangeRequest,
    GrantIdentity,
    GrantMintError,
    mint_grant,
)
from zebra_host_grant_broker.keys import jwk_document, load_private_key
from zebra_host_grant_broker.trench_session import TrenchSessionError, fetch_viewer
from zebra_host_grant_broker.workload_auth import WorkloadAuthError, verify_workload


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
        http_request: Request,
        response: Response,
        authorization: Annotated[str | None, Header()] = None,
        cookie: Annotated[str | None, Header()] = None,
        workload_identity: Annotated[str | None, Header(alias="X-Zebra-Workload-Identity")] = None,
        workload_timestamp: Annotated[
            str | None, Header(alias="X-Zebra-Workload-Timestamp")
        ] = None,
        workload_nonce: Annotated[str | None, Header(alias="X-Zebra-Workload-Nonce")] = None,
        workload_signature: Annotated[
            str | None, Header(alias="X-Zebra-Workload-Signature")
        ] = None,
    ) -> dict[str, str]:
        try:
            body_data = await http_request.json()
            request = ExchangeRequest.parse(body_data)
            request.enforce(settings)
            verified_workload = None
            expires_at = None
            viewer: GrantIdentity
            if settings.authority_mode == "generic":
                headers = {"Accept": "application/json"}
                if authorization or (cookie and cookie.strip()):
                    if authorization:
                        if not authorization.startswith("Bearer ") or not authorization[7:].strip():
                            raise AuthorityError("credential_invalid")
                        headers["Authorization"] = authorization
                    if cookie and cookie.strip():
                        headers["Cookie"] = cookie
                else:
                    verified_workload = verify_workload(
                        settings,
                        body_data,
                        identity=workload_identity,
                        timestamp=workload_timestamp,
                        nonce=workload_nonce,
                        signature=workload_signature,
                    )
                    for name, value in (
                        ("Identity", workload_identity),
                        ("Timestamp", workload_timestamp),
                        ("Nonce", workload_nonce),
                        ("Signature", workload_signature),
                    ):
                        if value is not None:
                            headers[f"X-Zebra-Workload-{name}"] = value
                authority = fetch_authority(
                    settings,
                    body_data,
                    headers,
                    expected_principal=(
                        verified_workload.viewer.user_id if verified_workload else None
                    ),
                    expected_workspace=(
                        verified_workload.viewer.workspace_id if verified_workload else None
                    ),
                )
                authority.authorize(request)
                viewer = authority
                expires_at = authority.expires_at
            else:
                if cookie and cookie.strip():
                    viewer = fetch_viewer(
                        settings.trench_me_url,
                        settings.trench_sources_url,
                        cookie.strip(),
                        timeout_seconds=settings.trench_timeout_seconds,
                    )
                else:
                    verified_workload = verify_workload(
                        settings,
                        body_data,
                        identity=workload_identity,
                        timestamp=workload_timestamp,
                        nonce=workload_nonce,
                        signature=workload_signature,
                    )
                    viewer = verified_workload.viewer
                request.authorize(viewer)
            grant = mint_grant(
                settings,
                signing_key,
                request,
                viewer,
                expires_at=expires_at,
                jti=verified_workload.grant_id if verified_workload is not None else None,
            )
        except (ValueError, TypeError) as exc:
            if isinstance(exc, WorkloadAuthError | AuthorityError):
                response.status_code = 401
            else:
                response.status_code = 400
            reason = (
                str(exc)
                if isinstance(exc, GrantMintError | WorkloadAuthError | AuthorityError)
                else "request_body_invalid"
            )
            return {"status": "rejected", "reason": reason}
        except TrenchSessionError as exc:
            response.status_code = 401 if str(exc) == "session_inactive" else 502
            return {"status": "rejected", "reason": str(exc)}
        return {"grant": grant}

    return app
