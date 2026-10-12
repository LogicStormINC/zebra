"""Native run-owned MODEL publication consumes its owner's verified acknowledgement."""

from collections.abc import Callable
from datetime import datetime
from hashlib import sha256
from typing import cast

from agent_core.domain.artifact_payloads import ArtifactPayloadLifecycleStatus, ArtifactPayloadWrite
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_core.domain.coverage_model_checkpoint import (
    MODEL_CHECKPOINT_KIND,
    decode_model_checkpoint,
    model_checkpoint_id,
)
from agent_core.domain.identifiers import ArtifactId
from agent_integrations.coverage_snapshot_artifacts import CoverageArtifacts
from agent_storage.postgres.work_unit import borrow_work_unit

from zebra_agent_worker.coverage_artifacts import CloudCoverageArtifacts


class NativeCoverageArtifacts(CoverageArtifacts):
    def _publish(
        self, identifier: ArtifactId, kind: str, body: bytes, maximum: int,
        validate: Callable[[], datetime], expires_at: datetime, *,
        mime_type: str = "application/octet-stream",
    ) -> str:
        from zebra_agent_worker.coverage_native_model import qualified_checkpoint_publication

        # Only full-binding-derived checkpoint IDs use this owner. Manifest/body
        # IDs have different legacy reuse semantics and keep the generic path.
        if kind != MODEL_CHECKPOINT_KIND or not qualified_checkpoint_publication(self, validate):
            return super()._publish(
                identifier, kind, body, maximum, validate, expires_at, mime_type=mime_type,
            )
        source = cast(CloudCoverageArtifacts, self.store)
        if borrow_work_unit((source.metadata._database._dsn, source.deployment)) is not None:
            return super()._publish(
                identifier, kind, body, maximum, validate, expires_at, mime_type=mime_type,
            )
        now = validate()
        if len(body) > maximum:
            raise CoverageRefusedError(CoverageRefusalReason.BUDGET_EXCEEDED)
        try:
            checkpoint = decode_model_checkpoint(body)
            if (checkpoint.binding != source.binding
                    or identifier != model_checkpoint_id(checkpoint.binding, checkpoint.reservation)
                    or body != checkpoint.canonical_bytes):
                raise ValueError("MODEL publication does not bind its checkpoint identity")
            stored = source.store_payload_immutable(
                ArtifactPayloadWrite(
                    session_id=self.session, kind=kind, mime_type=mime_type,
                    payload=body, created_at=now, retained_until=expires_at,
                ), artifact_id=identifier,
            )
            current = validate()
            if (stored.artifact_id != identifier or stored.session_id != self.session
                    or stored.uri != f"artifact://{identifier}" or stored.kind != kind
                    or stored.mime_type != mime_type
                    or stored.lifecycle_status != ArtifactPayloadLifecycleStatus.ACTIVE
                    or stored.pruned_at is not None or stored.size_bytes != len(body)
                    or stored.sha256 != sha256(body).hexdigest()
                    or stored.created_at > current or stored.retained_until != expires_at
                    or expires_at <= current):
                raise ValueError("native MODEL publication acknowledgement conflicts")
            # Actual publisher I/O, final callbacks and post-lock SQL validation
            # have finished. Later _required reads and final proof stay independent.
            return stored.uri
        except (OSError, ValueError) as error:
            raise CoverageRefusedError(CoverageRefusalReason.ARTIFACT_UNAVAILABLE) from error
