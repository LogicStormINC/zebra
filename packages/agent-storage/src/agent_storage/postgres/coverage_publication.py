"""Certificate issuance is one fenced Event transaction over exact accepted facts."""

import json
from collections.abc import Callable
from contextlib import nullcontext
from datetime import datetime
from typing import Any

from agent_core.domain.coverage_contracts import coverage_digest
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.coverage_report import CoverageReport
from agent_core.domain.coverage_validation import (
    AcceptedCoverageUnit,
    CoverageCertificate,
    expected_units,
)
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.leases import LeaseFence

from agent_storage.postgres.coverage_artifacts import (
    read_artifact,
    read_manifest,
)
from agent_storage.postgres.coverage_model_acceptance import (
    ModelObservationDeriver,
    pin_evidence,
)
from agent_storage.postgres.coverage_model_checkpoint import check_checkpoint_retention
from agent_storage.postgres.coverage_model_source import certify_model_budget, task_policy
from agent_storage.postgres.coverage_model_verification import _ModelVerification
from agent_storage.postgres.coverage_projection import project_watermark
from agent_storage.postgres.coverage_transactions import (
    append_coverage_event,
    assert_projection,
    lock_run,
    validate_write,
)


class CoveragePublicationQueries:
    _database: Any
    _deployment: str
    _artifacts: Any
    _model_observation_deriver: ModelObservationDeriver | None

    def _binding(self, namespace: str, run_id: str) -> CoverageRunBinding:
        raise NotImplementedError

    def _check_publication_lifecycle(
        self,
        connection: Any,
        binding: CoverageRunBinding,
        report_ref: str,
        report_digest: str,
        retention_deadlines: list[datetime],
    ) -> None:
        """Under lock_run, pin co-located Cloud evidence until transaction completion."""
        scope = getattr(self._artifacts, "_locked_proof_scope", None)
        with (scope(
            connection, self._deployment, binding, derive=self._model_observation_deriver,
            final_certification=True,
        ) if callable(scope) else nullcontext(self._artifacts)) as artifacts:
            self._verify_publication_lifecycle(
                connection, binding, report_ref, report_digest, retention_deadlines, artifacts,
            )

    def _verify_publication_lifecycle(
        self, connection: Any, binding: CoverageRunBinding, report_ref: str,
        report_digest: str, retention_deadlines: list[datetime], artifacts: Any,
    ) -> None:
        row = connection.execute(
            """SELECT * FROM coverage_runs WHERE deployment_namespace=%s
               AND namespace=%s AND run_id=%s""",
            (self._deployment, binding.namespace, binding.run_id),
        ).fetchone()
        if row is None or row["cancelled"]:
            raise ValueError("coverage run is cancelled or unavailable")
        assert_projection(connection, self._deployment, binding, row)
        now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        issued = connection.execute(
            """SELECT created_at FROM session_events WHERE deployment_namespace=%s AND session_id=%s
               AND event_type='coverage_report_certified' AND payload->>'namespace'=%s
               AND payload->>'run_id'=%s ORDER BY sequence""",
            (self._deployment, binding.session_id, binding.namespace, binding.run_id),
        ).fetchall()
        if len(issued) > 1:
            raise ValueError("coverage has conflicting certificate source Events")
        certify_model_budget(
            connection,
            self._deployment,
            binding,
            at=issued[0]["created_at"] if issued else now,
            artifacts=artifacts,
            retention_deadlines=retention_deadlines,
        )
        if not binding.snapshot.as_of <= now < binding.snapshot.expires_at:
            raise ValueError("coverage certificate has expired")
        stopped = connection.execute(
            """SELECT 1 FROM session_events WHERE deployment_namespace=%s AND session_id=%s
               AND (event_type IN ('session_cancelled','session_failed')
                 OR (event_type='session_command_accepted'
                     AND payload->>'kind' IN ('stop','cancel')))
               LIMIT 1""",
            (self._deployment, binding.session_id),
        ).fetchone()
        if stopped is not None:
            raise ValueError("coverage Session is terminal or has accepted STOP/cancel")
        refs = [
            (binding.snapshot.manifest_artifact_ref, binding.manifest_artifact_digest),
            (report_ref, report_digest),
        ]
        cursor = -1
        while True:
            for ref, digest in refs:
                pin_evidence(
                    connection,
                    self._deployment,
                    binding,
                    artifacts,
                    ref,
                    digest,
                    retention_deadlines,
                )
            rows = connection.execute(
                """SELECT payload,sequence FROM session_events WHERE deployment_namespace=%s
                   AND session_id=%s AND event_type='coverage_batch_accepted'
                   AND payload->>'namespace'=%s AND payload->>'run_id'=%s
                   AND sequence>%s ORDER BY sequence LIMIT 100""",
                (self._deployment, binding.session_id, binding.namespace, binding.run_id, cursor),
            ).fetchall()
            if not rows:
                break
            refs = [
                (
                    row["payload"]["request"]["result_artifact_ref"],
                    row["payload"]["request"]["result_artifact_digest"],
                )
                for row in rows
            ]
            cursor = rows[-1]["sequence"]
        accepted = self._accepted_results(connection, binding)
        transcript = self._verify_result_sources(connection, binding, accepted, artifacts=artifacts)
        transcript.verify(accepted, deadlines=retention_deadlines)
        # ponytail: SQLite metadata lives in another database; this final reader
        # check detects observed races, but atomic pruning needs co-located rows.

    def _accepted_results(
        self, connection: Any, binding: CoverageRunBinding
    ) -> tuple[AcceptedCoverageUnit, ...]:
        rows = connection.execute(
            """SELECT result FROM coverage_units WHERE deployment_namespace=%s
               AND namespace=%s AND run_id=%s AND result IS NOT NULL ORDER BY ordinal
               LIMIT 200001""",
            (self._deployment, binding.namespace, binding.run_id),
        ).fetchall()
        if len(rows) > 200000:
            raise ValueError("coverage accepted set exceeds validation bound")
        return tuple(AcceptedCoverageUnit.model_validate(row["result"]) for row in rows)

    def _verify_result_sources(
        self,
        connection: Any,
        binding: CoverageRunBinding,
        accepted: tuple[AcceptedCoverageUnit, ...],
        *, artifacts: Any = None,
    ) -> _ModelVerification:
        expected = {item.key: item for item in accepted}
        seen = set()
        transcript = _ModelVerification(
            connection, self._deployment, binding,
            artifacts=self._artifacts if artifacts is None else artifacts,
            derive=self._model_observation_deriver,
        )
        for sequence, request, _ in transcript.batches():
            transcript.verify(
                request.results, deadlines=[], request=request, before_sequence=sequence,
            )
            for item in request.results:
                if item.key in seen or expected.get(item.key) != item:
                    raise ValueError("accepted coverage disagrees with source Artifacts")
                seen.add(item.key)
        if seen != set(expected):
            raise ValueError("accepted coverage has missing source Artifact evidence")
        return transcript

    def accepted_page(
        self, namespace: str, run_id: str, *, limit: int = 100, after_ordinal: int = -1
    ) -> tuple[tuple[int, AcceptedCoverageUnit], ...]:
        if type(limit) is not int or not 1 <= limit <= 1000 or type(after_ordinal) is not int:
            raise ValueError("invalid coverage result page")
        if after_ordinal < -1:
            raise ValueError("invalid coverage cursor")
        with self._database.connect() as connection:
            rows = connection.execute(
                """SELECT ordinal,result FROM coverage_units WHERE deployment_namespace=%s
                   AND namespace=%s AND run_id=%s AND result IS NOT NULL AND ordinal>%s
                   ORDER BY ordinal LIMIT %s""",
                (self._deployment, namespace, run_id, after_ordinal, limit),
            ).fetchall()
            return tuple(
                (int(row["ordinal"]), AcceptedCoverageUnit.model_validate(row["result"]))
                for row in rows
            )

    def certify(
        self,
        namespace: str,
        run_id: str,
        *,
        report_ref: str,
        report_digest: str,
        fence: LeaseFence,
        check_authority: Callable[[], None],
    ) -> CoverageCertificate:
        """Authority checks under the fence must be read-only.

        Final checks must not re-enter locked database mutations. The two early
        checks run before locking so callback-driven cancellation can complete.
        """
        binding = self._binding(namespace, run_id)
        check_authority()
        records = read_manifest(self._artifacts, binding)
        body = read_artifact(self._artifacts, report_ref, report_digest, binding.session_id)
        report = CoverageReport.model_validate(json.loads(body))
        if report.canonical_bytes != body:
            raise ValueError("coverage report is not canonical")
        # The callback may synchronously cancel; acquire lifecycle locks afterwards.
        check_authority()
        from agent_storage.postgres.work_unit import postgres_work_unit

        with postgres_work_unit(self._database), self._database.connect() as connection:
            row, version = lock_run(connection, self._deployment, binding, fence)
            deadlines: list[datetime] = []
            assert_projection(connection, self._deployment, binding, row)
            if row["cancelled"]:
                raise ValueError("cancelled coverage cannot publish")
            rows = connection.execute(
                """SELECT unit_key,result FROM coverage_units WHERE deployment_namespace=%s
                   AND namespace=%s AND run_id=%s ORDER BY ordinal LIMIT 200001""",
                (self._deployment, namespace, run_id),
            ).fetchall()
            if len(rows) > 200000 or any(item["result"] is None for item in rows):
                raise ValueError("coverage is incomplete or exceeds report validation bound")
            accepted = tuple(AcceptedCoverageUnit.model_validate(item["result"]) for item in rows)
            expected = expected_units(binding.contract, records, max_units=200000)
            if len(set(expected)) != len(expected) or set(expected) != {
                item.key for item in accepted
            }:
                raise ValueError("coverage expected/accepted exact sets disagree")
            report.validate_for(binding, accepted)
            # Deny incomplete/mismatched sets before expensive original proof.
            # Complete sets still require every lifecycle and MODEL gate below.
            self._check_publication_lifecycle(
                connection, binding, report_ref, report_digest, deadlines
            )
            now, _, _ = validate_write(connection, self._deployment, binding, fence)
            prior = connection.execute(
                """SELECT payload,sequence FROM session_events WHERE deployment_namespace=%s
                   AND session_id=%s AND event_type='coverage_report_certified'
                   AND payload->>'namespace'=%s AND payload->>'run_id'=%s ORDER BY sequence""",
                (self._deployment, binding.session_id, namespace, run_id),
            ).fetchall()
            if prior:
                if len(prior) != 1 or prior[0]["payload"]["report_ref"] != report_ref:
                    raise ValueError("coverage certificate publication conflicts")
                certificate = CoverageCertificate.model_validate(prior[0]["payload"]["certificate"])
                if certificate.report_digest != report_digest:
                    raise ValueError("coverage certificate report changed")
                report.validate_certificate(binding, certificate, watermark=prior[0]["sequence"])
                self._check_publication_lifecycle(
                    connection, binding, report_ref, report_digest, deadlines
                )
                check_authority()
                validate_write(connection, self._deployment, binding, fence)
                check_checkpoint_retention(connection, deadlines)
                return certificate
            certificate = CoverageCertificate(
                namespace=namespace,
                host_id=binding.snapshot.host_id,
                snapshot_id=binding.snapshot.snapshot_id,
                authority_revision=binding.snapshot.authority_revision,
                contract_revision=binding.contract.contract_revision,
                contract_digest=binding.contract.digest,
                scope_digest=binding.contract.scope.digest,
                manifest_digest=binding.snapshot.manifest_digest,
                enumerated_records=len(records),
                read_parts=sum(len(record.parts) for record in records),
                processed_units=len(accepted),
                reviewed_units=0,
                result_set_digest=report.result_set_digest,
                aggregate_digest=coverage_digest(report.model_dump(mode="json")),
                report_digest=report_digest,
                validator_version="exact-artifact/1",
                event_watermark=version + 1,
                created_at=now,
                expires_at=binding.snapshot.expires_at,
            )
            report.validate_certificate(binding, certificate, watermark=version + 1)
            event = append_coverage_event(
                connection,
                self._deployment,
                binding,
                fence,
                version + 1,
                EventType.COVERAGE_REPORT_CERTIFIED,
                {
                    "certificate": certificate.model_dump(mode="json"),
                    "report_ref": report_ref,
                    "metadata": {"artifact_uri": report_ref},
                },
            )
            project_watermark(
                connection, self._deployment, binding, event.sequence, cancelled=False
            )
            connection.execute(
                """DELETE FROM coverage_continuations WHERE deployment_namespace=%s
                   AND namespace=%s AND run_id=%s""",
                (self._deployment, namespace, run_id),
            )
            if event.sequence != certificate.event_watermark:
                raise ValueError("coverage certificate Event watermark changed")
            self._check_publication_lifecycle(
                connection, binding, report_ref, report_digest, deadlines
            )
            check_authority()
            # ponytail: this branch is first issuance even after its uncommitted
            # Event exists. Historical replay time must not authorize late issuance.
            policy = task_policy(connection, self._deployment, binding)
            validate_write(connection, self._deployment, binding, fence)
            now = check_checkpoint_retention(connection, deadlines)
            if policy is not None and not policy.started_at <= now < policy.deadline:
                raise ValueError("first certification exceeded original MODEL deadline")
            return certificate

    def _replay_certificate(
        self,
        connection: Any,
        binding: CoverageRunBinding,
        event: SessionEvent,
        *,
        retention_deadlines: list[datetime] | None = None,
    ) -> None:
        deadlines = [] if retention_deadlines is None else retention_deadlines
        certificate = CoverageCertificate.model_validate(event.payload["certificate"])
        certify_model_budget(
            connection,
            self._deployment,
            binding,
            at=event.created_at,
            artifacts=self._artifacts,
            retention_deadlines=deadlines,
        )
        if certificate.created_at > event.created_at:
            raise ValueError("certificate timestamp follows source issuance")
        ref, digest = event.payload["report_ref"], certificate.report_digest
        pin_evidence(connection, self._deployment, binding, self._artifacts, ref, digest, deadlines)
        body = read_artifact(self._artifacts, ref, digest, binding.session_id)
        report = CoverageReport.model_validate(json.loads(body))
        rows = connection.execute(
            """SELECT result FROM coverage_units WHERE deployment_namespace=%s
               AND namespace=%s AND run_id=%s ORDER BY ordinal LIMIT 200001""",
            (self._deployment, binding.namespace, binding.run_id),
        ).fetchall()
        if len(rows) > 200000 or any(row["result"] is None for row in rows):
            raise ValueError("certificate preceded complete acceptance")
        accepted = tuple(AcceptedCoverageUnit.model_validate(row["result"]) for row in rows)
        transcript = self._verify_result_sources(connection, binding, accepted)
        transcript.verify(accepted, deadlines=deadlines)
        report.validate_for(binding, accepted)
        report.validate_certificate(binding, certificate, watermark=event.sequence)
        if (
            body != report.canonical_bytes
            or certificate.namespace != binding.namespace
            or certificate.snapshot_id != binding.snapshot.snapshot_id
            or certificate.host_id != binding.snapshot.host_id
            or certificate.contract_digest != binding.contract.digest
            or certificate.manifest_digest != binding.snapshot.manifest_digest
            or certificate.result_set_digest != report.result_set_digest
            or certificate.aggregate_digest != coverage_digest(report.model_dump(mode="json"))
            or certificate.processed_units != len(accepted)
            or certificate.event_watermark != event.sequence
        ):
            raise ValueError("certificate replay conflicts with authoritative facts")
        project_watermark(connection, self._deployment, binding, event.sequence, cancelled=False)
        connection.execute(
            """DELETE FROM coverage_continuations WHERE deployment_namespace=%s
               AND namespace=%s AND run_id=%s""",
            (self._deployment, binding.namespace, binding.run_id),
        )
        check_checkpoint_retention(connection, deadlines)

    def certificate(
        self, namespace: str, run_id: str, *, now: datetime, check_authority: Callable[[], None]
    ) -> tuple[CoverageCertificate, str] | None:
        """Preserve the original certificate-only contract and shared authority gate."""
        result = self.certified_report(
            namespace, run_id, now=now, check_authority=check_authority
        )
        return None if result is None else (result[0], result[1])

    def certified_report(
        self, namespace: str, run_id: str, *, now: datetime, check_authority: Callable[[], None],
        authority_expires_at: datetime | None = None,
    ) -> tuple[CoverageCertificate, str, bytes] | None:
        """Return exact validated bytes without a post-gate ordinary payload read."""
        from agent_storage.postgres.coverage_certificate_read import read_certified_report

        return read_certified_report(
            self, namespace, run_id, now=now, check_authority=check_authority,
            authority_expires_at=authority_expires_at,
        )
