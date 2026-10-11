"""Report generation must use exact accepted governed observations, never chat text."""

import json
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID

import pytest
from agent_core.application.coverage_executor import observation_id
from agent_core.domain.coverage_contracts import CoverageRefusedError, coverage_digest
from agent_core.domain.coverage_report import CoverageReport
from agent_core.domain.coverage_validation import CoverageCertificate
from agent_core.domain.identifiers import ArtifactId
from agent_storage.artifact_payloads import ArtifactPayloadMissingError

from tests.agent_core.test_coverage_executor import NOW, executor, setup_execution


def test_expected_unit_bound_refuses_before_allocating_keys(tmp_path, monkeypatch):
    from agent_core.domain.coverage_validation import expected_units

    env = setup_execution(tmp_path)
    monkeypatch.setattr(
        "agent_core.domain.coverage_validation.CoverageUnitKey",
        lambda **_: pytest.fail("unit allocated before count refusal"),
    )
    with pytest.raises(CoverageRefusedError):
        expected_units(env.binding.contract, env.records, max_units=2)


def test_report_refuses_large_expansion_before_reading_results(tmp_path, monkeypatch):
    env = setup_execution(tmp_path)
    run = executor(env)
    # Repeated records are only a cheap probe of count-first behavior, not accepted data.
    run.records = {str(i): env.records[0] for i in range(66667)}
    publication = Publication(env)
    monkeypatch.setattr(
        "agent_core.domain.coverage_validation.CoverageUnitKey",
        lambda **_: pytest.fail("expanded report before count refusal"),
    )
    with pytest.raises(CoverageRefusedError):
        run.publish_report(publication, fence=env.fence)
    assert publication.calls == [] and publication.certificates == []


class Publication:
    def __init__(self, env):
        self.env, self.calls, self.certificates = env, [], []
        self.page_size, self.bad_cursor, self.duplicate = 1, False, False
        self.lose_response = False

    def accepted_page(self, namespace, run_id, *, limit, after_ordinal):
        self.env.store.guard(namespace, run_id)
        self.calls.append(after_ordinal)
        rows = tuple(
            (i, self.env.store.accepted[key])
            for i, key in enumerate(self.env.store.units)
            if i > after_ordinal and key in self.env.store.accepted
        )[: min(limit, self.page_size)]
        if self.bad_cursor and rows:
            return ((after_ordinal, rows[0][1]),)
        if self.duplicate and rows and after_ordinal >= 0:
            return ((rows[0][0], next(iter(self.env.store.accepted.values()))),)
        return rows

    def certify(self, namespace, run_id, *, report_ref, report_digest, fence, check_authority):
        self.env.store.guard(namespace, run_id, fence)
        check_authority()
        identifier = ArtifactId(UUID(report_ref.removeprefix("artifact://")))
        body = self.env.artifacts.read_payload_bytes(identifier)
        assert sha256(body).hexdigest() == report_digest
        report = CoverageReport.model_validate(json.loads(body))
        report.validate_for(self.env.binding, tuple(self.env.store.accepted.values()))
        binding = self.env.binding
        certificate = CoverageCertificate(
            namespace=namespace,
            host_id=binding.snapshot.host_id,
            snapshot_id=binding.snapshot.snapshot_id,
            authority_revision=binding.snapshot.authority_revision,
            contract_revision=binding.contract.contract_revision,
            contract_digest=binding.contract.digest,
            scope_digest=binding.contract.scope.digest,
            manifest_digest=binding.snapshot.manifest_digest,
            enumerated_records=len(self.env.records),
            read_parts=sum(len(row.parts) for row in self.env.records),
            processed_units=len(report.observations),
            reviewed_units=0,
            result_set_digest=report.result_set_digest,
            aggregate_digest=coverage_digest(report.model_dump(mode="json")),
            report_digest=report_digest,
            validator_version="test/1",
            event_watermark=10,
            created_at=NOW,
            expires_at=binding.snapshot.expires_at,
        )
        self.certificates.append((certificate, report_ref))
        if self.lose_response:
            self.lose_response = False
            raise RuntimeError("lost certificate response")
        return certificate


def complete(tmp_path, *, bodies=(("risk", "safe"),)):
    env = setup_execution(tmp_path, bodies=bodies)
    execution = executor(env)
    while execution.execute_batch(fence=env.fence) != (len(env.store.units), len(env.store.units)):
        pass
    return SimpleNamespace(env=env, execution=execution, publication=Publication(env))


def test_report_preserves_positive_negative_and_merge_results(tmp_path):
    context = complete(tmp_path)
    certificate, ref = context.execution.publish_report(
        context.publication, fence=context.env.fence
    )
    report = CoverageReport.model_validate(json.loads(context.execution._bytes(ref)))
    assert len(report.observations) == 3
    assert [row.outcome for row in report.observations] == ["finding", "clear", "finding"]
    assert certificate.processed_units == 3
    assert context.publication.calls == [-1, 0, 1, 2]


def test_report_retry_after_lost_certificate_response_uses_same_artifact(tmp_path):
    context = complete(tmp_path)
    context.publication.lose_response = True
    with pytest.raises(RuntimeError, match="lost certificate"):
        context.execution.publish_report(context.publication, fence=context.env.fence)
    retry = context.execution.publish_report(context.publication, fence=context.env.fence)
    assert retry == context.publication.certificates[0]


def test_incomplete_report_cannot_publish(tmp_path):
    env = setup_execution(tmp_path)
    execution, publication = executor(env), Publication(env)
    execution.execute_batch(fence=env.fence, limit=1)
    with pytest.raises(ValueError, match="exact complete"):
        execution.publish_report(publication, fence=env.fence)
    assert publication.certificates == []


@pytest.mark.parametrize("fault", ["bad_cursor", "duplicate"])
def test_invalid_pages_never_certify(tmp_path, fault):
    context = complete(tmp_path)
    setattr(context.publication, fault, True)
    with pytest.raises(ValueError):
        context.execution.publish_report(context.publication, fence=context.env.fence)
    assert context.publication.certificates == []


def test_changed_accepted_outcome_never_certifies(tmp_path):
    context = complete(tmp_path)
    key = next(iter(context.env.store.accepted))
    context.env.store.accepted[key] = context.env.store.accepted[key].model_copy(
        update={"outcome": "clear"}
    )
    with pytest.raises(ValueError, match="differs"):
        context.execution.publish_report(context.publication, fence=context.env.fence)
    assert context.publication.certificates == []


def test_missing_observation_never_certifies(tmp_path):
    context = complete(tmp_path)
    key = next(iter(context.env.store.accepted))
    context.env.artifacts.prune_payload(observation_id(context.env.binding, key))
    with pytest.raises(ArtifactPayloadMissingError):
        context.execution.publish_report(context.publication, fence=context.env.fence)
    assert context.publication.certificates == []


def test_revoked_permission_never_certifies(tmp_path):
    context = complete(tmp_path)
    context.env.revoked = True
    with pytest.raises(CoverageRefusedError):
        context.execution.publish_report(context.publication, fence=context.env.fence)
    assert context.publication.certificates == []


def test_empty_scope_has_a_valid_empty_report_not_fake_observations(tmp_path):
    context = complete(tmp_path, bodies=())
    certificate, ref = context.execution.publish_report(
        context.publication, fence=context.env.fence
    )
    report = CoverageReport.model_validate(json.loads(context.execution._bytes(ref)))
    assert report.observations == ()
    assert certificate.enumerated_records == certificate.processed_units == 0


def test_multipart_report_preserves_all_findings_without_unbounded_merge_quotes(tmp_path):
    context = complete(tmp_path, bodies=(tuple("risk" for _ in range(101)),))
    _, ref = context.execution.publish_report(context.publication, fence=context.env.fence)
    report = CoverageReport.model_validate(json.loads(context.execution._bytes(ref)))
    parts, merge = report.observations[:-1], report.observations[-1]
    assert len(parts) == 101 and all(part.outcome == "finding" for part in parts)
    assert len(merge.quotes) == 100
    assert merge.part_result_digests == tuple(part.digest for part in parts)


@pytest.mark.parametrize(
    "field,value",
    [
        ("authority_revision", "another-grant"),
        ("scope_digest", "f" * 64),
        ("contract_revision", 99),
        ("enumerated_records", 99),
        ("read_parts", 99),
        ("processed_units", 99),
        ("reviewed_units", 1),
        ("validator_version", "unchecked/1"),
    ],
)
def test_certificate_all_binding_fields_are_verified(tmp_path, field, value):
    context = complete(tmp_path)
    certificate, ref = context.execution.publish_report(
        context.publication, fence=context.env.fence
    )
    certificate = certificate.model_copy(update={"validator_version": "exact-artifact/1"})
    report = CoverageReport.model_validate(json.loads(context.execution._bytes(ref)))
    report.validate_certificate(
        context.env.binding, certificate, watermark=certificate.event_watermark
    )
    with pytest.raises(ValueError, match="certificate binding"):
        report.validate_certificate(
            context.env.binding,
            certificate.model_copy(update={field: value}),
            watermark=certificate.event_watermark,
        )
