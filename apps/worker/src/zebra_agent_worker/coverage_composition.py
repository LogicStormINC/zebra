"""Explicit strict Worker composition; never inherit an ordinary provider client."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from agent_core.domain.coverage_contracts import CoverageRefusalReason as Reason
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.ports.artifact_object_store import ArtifactObjectStorePort
from agent_integrations.coverage_model_policy import (
    MAX_METADATA_BYTES,
    MODELS_URL,
    OfficialDeepSeekPolicy,
)
from agent_storage.postgres.artifact_payloads import PostgresCloudArtifactPayloadStore
from agent_storage.postgres.connection_scope import postgres_connection_scope

from zebra_agent_worker.execution_finalization import ExecutedSession, WorkerExecutionError


@dataclass(frozen=True)
class CloudCoverageRuntime:
    """The actual co-located Cloud dependencies, not a readiness flag."""

    dsn: str
    deployment_namespace: str
    metadata: PostgresCloudArtifactPayloadStore
    objects: ArtifactObjectStorePort

    @postgres_connection_scope()
    def recovery_check(
        self,
        service: Any,
        connection: Any,
        namespace: str,
        pending: dict[str, Any],
        receipt: dict[str, Any],
    ) -> dict[str, Any]:
        from zebra_agent_worker.coverage_recovery import verify_cloud_coverage_recovery

        return verify_cloud_coverage_recovery(
            self, service, connection, namespace, pending, receipt
        )

    def execute(
        self, service: Any, inputs: Any, recorder: Any, ownership_check: Callable[[], None]
    ) -> ExecutedSession:

        from zebra_agent_worker.coverage_dispatch import execute_cloud_coverage

        try:
            with postgres_connection_scope():
                return execute_cloud_coverage(self, service, inputs, recorder, ownership_check)
        except CoverageRefusedError as error:
            # Reuse the normal fenced failure/Turn cleanup without persisting
            # provider, credential, object-store or HTTP exception text.
            raise WorkerExecutionError(
                f"strict coverage refused: {error.reason.value}",
                coverage_refusal_reason=error.reason,
            ) from None


def load_official_model_policy(
    *,
    api_key: str,
    deadline: datetime,
    check_authority: Callable[[], None],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> OfficialDeepSeekPolicy:
    """Authenticate one bounded original metadata response on a fresh owned client.

    Credentials and response bodies never become diagnostic text. Parsing remains
    the integration's responsibility; no caller-supplied client grants origin proof.
    """
    if (
        type(api_key) is not str
        or not api_key.strip()
        or type(deadline) is not datetime
        or deadline.utcoffset() is None
        or not callable(check_authority)
        or not callable(now)
    ):
        raise CoverageRefusedError(Reason.UNSUPPORTED)

    def live() -> float:
        try:
            check_authority()
        except CoverageRefusedError:
            raise
        except Exception:
            raise CoverageRefusedError(Reason.AUTHORITY_INVALID) from None
        current = now()
        if type(current) is not datetime or current.utcoffset() is None or current >= deadline:
            raise CoverageRefusedError(Reason.BUDGET_EXCEEDED)
        return (deadline - current).total_seconds()

    remaining = live()
    try:
        with httpx.HTTPTransport(verify=True, trust_env=False, retries=0) as transport:
            with httpx.Client(
                transport=transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(min(10.0, remaining)),
            ) as client:
                with client.stream(
                    "GET", MODELS_URL, headers={"Authorization": f"Bearer {api_key}"}
                ) as response:
                    if response.status_code != 200:
                        raise CoverageRefusedError(Reason.UNSUPPORTED)
                    body = bytearray()
                    for chunk in response.iter_bytes(chunk_size=65536):
                        live()
                        if len(body) + len(chunk) > MAX_METADATA_BYTES:
                            raise CoverageRefusedError(Reason.UNSUPPORTED)
                        body.extend(chunk)
        live()
        return OfficialDeepSeekPolicy(bytes(body))
    except CoverageRefusedError:
        raise
    except (httpx.HTTPError, ValueError, TypeError, RecursionError, OverflowError):
        raise CoverageRefusedError(Reason.UNSUPPORTED) from None
