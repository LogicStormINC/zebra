"""Bounded resumable execution: accepted indexes, not chat history, drive progress."""

import json
import math
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime
from hashlib import sha256
from time import monotonic
from uuid import NAMESPACE_URL, UUID, uuid5

from agent_core.domain.artifact_payloads import (
    ArtifactPayloadLifecycleStatus,
    ArtifactPayloadWrite,
    StoredArtifactPayload,
)
from agent_core.domain.coverage_contracts import (
    CoverageRefusalReason,
    CoverageRefusedError,
    coverage_digest,
)
from agent_core.domain.coverage_execution import CoverageExecutionBudget, CoverageObservation
from agent_core.domain.coverage_persistence import (
    CoverageRunBinding,
    canonical_coverage_bytes,
    coverage_result_bytes,
)
from agent_core.domain.coverage_report import CoverageReport
from agent_core.domain.coverage_snapshot import CoveragePart, CoveragePartRead, CoverageRecord
from agent_core.domain.coverage_task_admission import coverage_admission_input
from agent_core.domain.coverage_validation import (
    AcceptedCoverageUnit,
    CoverageCertificate,
    CoverageUnitKey,
    expected_units,
    result_set_digest,
)
from agent_core.domain.identifiers import ArtifactId
from agent_core.domain.leases import LeaseFence
from agent_core.ports.artifact_payload_store import (
    ArtifactPayloadReadScopePort,
    ArtifactPayloadStorePort,
    BoundedArtifactPayloadReaderPort,
    ImmutableArtifactPayloadBatchStorePort,
    ImmutableArtifactPayloadStorePort,
    VerifiedArtifactPayloadReaderPort,
)
from agent_core.ports.coverage import CoverageCommit
from agent_core.ports.coverage_execution import (
    CoverageCheckRunnerPort,
    CoverageExecutionStorePort,
    CoveragePublicationStorePort,
)

MAX_BYTES = 32 * 1024 * 1024
MAX_UNITS = 200000


def observation_id(binding: CoverageRunBinding, key: CoverageUnitKey) -> ArtifactId:
    return ArtifactId(
        uuid5(
            NAMESPACE_URL,
            f"coverage-observation/1:{binding.session_id}:"
            f"{binding.run_id}:{binding.contract.digest}:"
            + sha256(canonical_coverage_bytes(key.model_dump(mode="json"))).hexdigest(),
        )
    )


class CoverageExecutor:
    def __init__(
        self,
        *,
        binding: CoverageRunBinding,
        records: tuple[CoverageRecord, ...],
        store: CoverageExecutionStorePort,
        artifacts: ArtifactPayloadStorePort,
        read: Callable[[CoverageRecord, CoveragePart], CoveragePartRead],
        runner: CoverageCheckRunnerPort,
        budget: CoverageExecutionBudget,
        check_authority: Callable[[], None],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not isinstance(artifacts, ImmutableArtifactPayloadStorePort) or not isinstance(
            artifacts, BoundedArtifactPayloadReaderPort
        ):
            raise CoverageRefusedError(CoverageRefusalReason.UNSUPPORTED)
        self.binding, self.records = binding, {row.record_id: row for row in records}
        if len(self.records) != len(records):
            raise ValueError("duplicate coverage record")
        if len(binding.contract.checks) * sum(len(row.parts) + 1 for row in records) > MAX_UNITS:
            raise CoverageRefusedError(CoverageRefusalReason.BUDGET_EXCEEDED)
        self.store, self.artifacts, self.read, self.runner = store, artifacts, read, runner
        self.budget, self.check_authority, self.now = budget, check_authority, now
        if binding.verify_manifest(self._bytes(
            binding.snapshot.manifest_artifact_ref, digest=binding.manifest_artifact_digest,
        )) != records:
            raise ValueError("executor records disagree with governed manifest")

    def _live(self) -> None:
        self.check_authority()
        if not self.binding.snapshot.as_of <= self.now() < self.binding.snapshot.expires_at:
            raise CoverageRefusedError(CoverageRefusalReason.SNAPSHOT_EXPIRED)

    def _bytes(
        self, ref: str, *, digest: str | None = None,
        reader: ArtifactPayloadStorePort | None = None,
    ) -> bytes:
        artifacts = self.artifacts if reader is None else reader
        identifier = ArtifactId(UUID(ref.removeprefix("artifact://")))
        if ref != f"artifact://{identifier}":
            raise ValueError("coverage requires canonical Artifact reference")
        metadata: StoredArtifactPayload | None
        if digest is not None and isinstance(artifacts, VerifiedArtifactPayloadReaderPort):
            metadata, body = artifacts.read_payload_verified_bounded(
                identifier, session_id=self.binding.session_id, digest=digest, max_bytes=MAX_BYTES,
            )
        else:
            metadata = artifacts.get_payload(identifier)
            if metadata is None or metadata.session_id != self.binding.session_id:
                raise ValueError("coverage Artifact belongs to another Session")
            assert isinstance(artifacts, BoundedArtifactPayloadReaderPort)
            body = artifacts.read_payload_bytes_bounded(identifier, max_bytes=MAX_BYTES)
        if (
            metadata is None or metadata.artifact_id != identifier
            or metadata.session_id != self.binding.session_id or metadata.uri != ref
            or metadata.lifecycle_status != ArtifactPayloadLifecycleStatus.ACTIVE
            or metadata.pruned_at is not None
            or (metadata.retained_until is not None and metadata.retained_until <= self.now())
            or len(body) > MAX_BYTES or len(body) != metadata.size_bytes
            or sha256(body).hexdigest() != metadata.sha256
            or (digest is not None and metadata.sha256 != digest)
        ):
            raise ValueError("coverage Artifact identity, retention or integrity conflicts")
        return body

    def _read_scope(
        self, identifiers: tuple[ArtifactId, ...],
    ) -> AbstractContextManager[ArtifactPayloadStorePort]:
        # ponytail: bounded readonly phase, never a model invocation or commit.
        # Oversized legacy records retain guarded per-getter reads.
        if (0 < len(identifiers) <= 1000
                and isinstance(self.artifacts, ArtifactPayloadReadScopePort)):
            return self.artifacts.read_payload_scope(tuple(dict.fromkeys(identifiers)))
        return nullcontext(self.artifacts)

    def _publish(self, identifier: ArtifactId, kind: str, body: bytes) -> str:
        self._live()
        if len(body) > MAX_BYTES:
            raise CoverageRefusedError(CoverageRefusalReason.BUDGET_EXCEEDED)
        assert isinstance(self.artifacts, ImmutableArtifactPayloadStorePort)
        existing = self.artifacts.get_payload(identifier)
        if existing is not None:
            if (
                existing.session_id != self.binding.session_id
                or existing.kind != kind
                or existing.mime_type != "application/octet-stream"
                or existing.retained_until != self.binding.snapshot.expires_at
                or self._bytes(existing.uri, digest=sha256(body).hexdigest()) != body
            ):
                raise ValueError("coverage Artifact identity conflict")
            return existing.uri
        stored = self.artifacts.store_payload_immutable(
            ArtifactPayloadWrite(
                session_id=self.binding.session_id,
                kind=kind,
                mime_type="application/octet-stream",
                payload=body,
                created_at=self.now(),
                retained_until=self.binding.snapshot.expires_at,
            ),
            artifact_id=identifier,
        )
        self._live()
        if self._bytes(stored.uri, digest=sha256(body).hexdigest()) != body:
            raise ValueError("coverage Artifact publication verification failed")
        return stored.uri

    def _prior(
        self, key: CoverageUnitKey, record: CoverageRecord
    ) -> tuple[CoverageObservation, ...]:
        accepted = self.store.accepted_for_record(
            self.binding.namespace, self.binding.run_id, record.record_id, check_id=key.check_id
        )
        indexed = {item.key: item for item in accepted}
        if len(indexed) != len(accepted):
            raise ValueError("accepted part index contains duplicate identities")
        prior = []
        prior_bytes = 0
        identifiers = tuple(observation_id(self.binding, result.key) for result in accepted)
        with self._read_scope(identifiers) as reader:
            for part in record.parts:
                part_key = key.model_copy(update={
                    "kind": "part", "part_id": part.id, "part_digest": part.digest,
                })
                result = indexed.get(part_key)
                if result is None:
                    raise ValueError(
                        "record merge attempted before every matching part was accepted"
                    )
                payload = self._bytes(
                    f"artifact://{observation_id(self.binding, result.key)}",
                    digest=result.result_digest, reader=reader,
                )
                prior_bytes += len(payload)
                if prior_bytes > MAX_BYTES:
                    raise CoverageRefusedError(CoverageRefusalReason.BUDGET_EXCEEDED)
                observation = CoverageObservation.model_validate(json.loads(payload))
                if (observation.key != result.key or observation.digest != result.result_digest
                        or observation.outcome != result.outcome):
                    raise ValueError("accepted observation Artifact conflicts")
                prior.append(observation)
        return tuple(prior)

    def execute_batch(
        self, *, fence: LeaseFence, limit: int = 100,
        max_input_bytes: int | None = None, max_seconds: float | None = None,
        batch_commits: bool = False,
    ) -> tuple[int, int]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("invalid coverage work unit limit")
        if type(batch_commits) is not bool:
            raise ValueError("invalid coverage batch commit mode")
        if max_input_bytes is not None and (
            type(max_input_bytes) is not int or not 1 <= max_input_bytes <= MAX_BYTES
        ):
            raise ValueError("invalid coverage work byte limit")
        if max_seconds is not None and (
            type(max_seconds) not in (int, float)
            or not math.isfinite(max_seconds) or not 0 < max_seconds <= 60
        ):
            raise ValueError("invalid coverage work time limit")
        started, consumed, completed = monotonic(), 0, 0
        self._live()
        self.store.bind(self.binding, fence=fence)
        missing = self.store.missing_units(self.binding.namespace, self.binding.run_id, limit=limit)
        buffered: list[AcceptedCoverageUnit] = []
        pending: list[tuple[ArtifactId, ArtifactPayloadWrite]] = []
        pending_bytes = 0
        batch_artifacts = batch_commits and isinstance(
            self.artifacts, ImmutableArtifactPayloadBatchStorePort
        )
        if batch_commits:
            # Reorder only this bounded page, never scan history. Parts commit
            # before merges, whose prior proof must come from the durable index.
            missing = tuple(sorted(missing, key=lambda item: item[1].kind == "record_merge"))
        for _, key in missing:
            self._live()
            record = self.records.get(key.record_id)
            if record is None or record.content_digest != key.content_digest:
                raise ValueError("missing-unit index disagrees with manifest")
            parts = (
                record.parts
                if key.kind == "record_merge"
                else tuple(
                    part
                    for part in record.parts
                    if part.id == key.part_id and part.digest == key.part_digest
                )
            )
            if not parts:
                raise ValueError("coverage unit has no bound canonical part")
            input_bytes = sum(part.byte_length for part in parts)
            if completed and (
                (max_seconds is not None and monotonic() - started >= max_seconds)
                or (max_input_bytes is not None and consumed + input_bytes > max_input_bytes)
            ):
                break
            # ponytail: one admitted unit may exceed the slice byte/time target;
            # finish it under task limits so large legal units cannot starve.
            # ponytail: bounded in-memory merge; larger records need streaming
            # evidence validation, not an arbitrarily larger Worker heap.
            if input_bytes > MAX_BYTES:
                raise CoverageRefusedError(CoverageRefusalReason.BUDGET_EXCEEDED)
            if key.kind == "record_merge" and buffered and buffered[0].key.kind != key.kind:
                self._commit_results(tuple(buffered), fence, payloads=tuple(pending))
                buffered.clear()
                pending.clear()
                pending_bytes = 0
            prior = self._prior(key, record) if key.kind == "record_merge" else ()
            self.store.reserve_attempt(
                self.binding, key, input_bytes=input_bytes, budget=self.budget, fence=fence
            )
            bodies = {}
            reads = tuple(self.read(record, part) for part in parts)
            with self._read_scope(tuple(
                ArtifactId(UUID(read.artifact_ref.removeprefix("artifact://"))) for read in reads
            )) as reader:
                for part, read in zip(parts, reads, strict=True):
                    if (
                        read.namespace != self.binding.namespace
                        or read.snapshot_id != self.binding.snapshot.snapshot_id
                        or read.record_id != record.record_id
                        or read.part != part
                        or read.content_digest != record.content_digest
                    ):
                        raise ValueError("body reader changed coverage identity")
                    payload = self._bytes(read.artifact_ref, digest=part.digest, reader=reader)
                    part.verify_bytes(payload)
                    bodies[part.id] = payload.decode("utf-8", errors="strict")
            self._live()
            identifier = observation_id(self.binding, key)
            existing = self.artifacts.get_payload(identifier)
            if existing is None:
                observation = self.runner.run(key, bodies, prior=prior)
                observation = CoverageObservation.model_validate(
                    coverage_admission_input(observation), strict=True
                )
                if observation.key != key:
                    raise ValueError("check runner returned a different coverage identity")
                observation.validate_source(bodies)
                body = canonical_coverage_bytes(observation.model_dump(mode="json"))
                if batch_artifacts and len(body) <= MAX_BYTES // 2:
                    if buffered and (len(buffered) >= 999
                                     or pending_bytes + len(body) > MAX_BYTES // 2):
                        self._commit_results(tuple(buffered), fence, payloads=tuple(pending))
                        buffered.clear()
                        pending.clear()
                        pending_bytes = 0
                    pending.append((identifier, self._payload("coverage_observation", body)))
                    pending_bytes += len(body)
                else:
                    self._publish(identifier, "coverage_observation", body)
            else:
                observation = CoverageObservation.model_validate(
                    json.loads(self._bytes(existing.uri, digest=existing.sha256))
                )
                if observation.key != key:
                    raise ValueError("recovered observation identity conflicts")
                observation.validate_source(bodies)
            result = AcceptedCoverageUnit(
                key=key, result_digest=observation.digest, outcome=observation.outcome
            )
            if batch_commits:
                buffered.append(result)
            else:
                self._commit_results((result,), fence)
            consumed += input_bytes
            completed += 1
        if buffered:
            self._commit_results(tuple(buffered), fence, payloads=tuple(pending))
        return self.store.counts(self.binding.namespace, self.binding.run_id)

    def _payload(self, kind: str, body: bytes) -> ArtifactPayloadWrite:
        return ArtifactPayloadWrite(
            session_id=self.binding.session_id, kind=kind,
            mime_type="application/octet-stream", payload=body, created_at=self.now(),
            retained_until=self.binding.snapshot.expires_at,
        )

    def _commit_results(
        self, results: tuple[AcceptedCoverageUnit, ...], fence: LeaseFence, *,
        payloads: tuple[tuple[ArtifactId, ArtifactPayloadWrite], ...] = (),
    ) -> None:
        body = coverage_result_bytes(results)
        digest = sha256(body).hexdigest()
        # Keep singleton identity compatible with interrupted legacy executors.
        identity = str(observation_id(self.binding, results[0].key)) if len(results) == 1 else (
            coverage_digest(self.binding.model_dump(mode="json"))
        )
        batch_id = ArtifactId(uuid5(NAMESPACE_URL, f"coverage-batch/1:{identity}:{digest}"))
        if payloads:
            assert isinstance(self.artifacts, ImmutableArtifactPayloadBatchStorePort)
            self._live()
            writes = (*payloads, (batch_id, self._payload("coverage_results", body)))
            if sum(len(payload.payload) for _, payload in writes) > MAX_BYTES:
                raise CoverageRefusedError(CoverageRefusalReason.BUDGET_EXCEEDED)
            stored = self.artifacts.store_payloads_immutable(writes)
            if len(stored) != len(writes):
                raise ValueError("coverage Artifact batch returned incomplete metadata")
            for item, (identifier, payload) in zip(stored, writes, strict=True):
                if (item.artifact_id != identifier or item.session_id != self.binding.session_id
                        or item.uri != f"artifact://{identifier}" or item.kind != payload.kind
                        or item.mime_type != payload.mime_type or item.pruned_at is not None
                        or item.lifecycle_status != ArtifactPayloadLifecycleStatus.ACTIVE
                        or item.retained_until != payload.retained_until
                        or item.sha256 != sha256(payload.payload).hexdigest()
                        or item.size_bytes != len(payload.payload)):
                    raise ValueError("coverage Artifact batch metadata conflicts")
            uri = stored[-1].uri
        else:
            uri = self._publish(batch_id, "coverage_results", body)
        self._live()
        self.store.commit(CoverageCommit(
            namespace=self.binding.namespace, session_id=self.binding.session_id,
            task_id=self.binding.task_id, run_id=self.binding.run_id,
            snapshot_id=self.binding.snapshot.snapshot_id,
            contract_digest=self.binding.contract.digest,
            manifest_digest=self.binding.snapshot.manifest_digest, commit_key=str(batch_id),
            result_artifact_ref=uri, result_artifact_digest=digest, results=results,
        ), fence=fence)

    def publish_report(
        self, publication: CoveragePublicationStorePort, *, fence: LeaseFence
    ) -> tuple[CoverageCertificate, str]:
        """Build only from accepted governed observations; certify separately and atomically."""
        self._live()
        expected = expected_units(
            self.binding.contract, tuple(self.records.values()), max_units=MAX_UNITS
        )
        accepted: list[AcceptedCoverageUnit] = []
        observations: list[CoverageObservation] = []
        cursor = -1
        observation_bytes = 0
        while True:
            self._live()
            page = publication.accepted_page(
                self.binding.namespace, self.binding.run_id, limit=1000, after_ordinal=cursor
            )
            if not page:
                break
            if len(page) > 1000 or len(accepted) + len(page) > len(expected):
                raise ValueError("report result page exceeds the bound expected set")
            with self._read_scope(tuple(
                observation_id(self.binding, result.key) for _, result in page
            )) as reader:
                for ordinal, result in page:
                    if type(ordinal) is not int or ordinal <= cursor:
                        raise ValueError("report result cursor did not advance")
                    payload = self._bytes(
                        f"artifact://{observation_id(self.binding, result.key)}",
                        digest=result.result_digest, reader=reader,
                    )
                    observation_bytes += len(payload)
                    if observation_bytes > MAX_BYTES:
                        raise CoverageRefusedError(CoverageRefusalReason.BUDGET_EXCEEDED)
                    observation = CoverageObservation.model_validate(json.loads(payload))
                    accepted.append(result)
                    observations.append(observation)
                    cursor = ordinal
            self._live()
        if len(accepted) != len(expected) or {item.key for item in accepted} != set(expected):
            raise ValueError("report requires the exact complete accepted set")
        report = CoverageReport(
            schema="coverage-report/1",
            binding_digest=coverage_digest(self.binding.model_dump(mode="json")),
            result_set_digest=result_set_digest(tuple(accepted)),
            observations=tuple(observations),
        )
        report.validate_for(self.binding, tuple(accepted))
        body = report.canonical_bytes
        digest = sha256(body).hexdigest()
        identifier = ArtifactId(
            uuid5(NAMESPACE_URL, f"coverage-report/1:{report.binding_digest}:{digest}")
        )
        ref = self._publish(identifier, "coverage_report", body)
        self._live()
        certificate = publication.certify(
            self.binding.namespace,
            self.binding.run_id,
            report_ref=ref,
            report_digest=digest,
            fence=fence,
            check_authority=self._live,
        )
        self._live()
        return certificate, ref
