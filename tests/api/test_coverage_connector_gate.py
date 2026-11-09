"""Strict orchestration still refuses a currently unavailable Host connector."""

from zebra_agent_api.coverage_http_admission import CoverageHttpAdmission

from tests.api.test_coverage_http_admission import composed_app, grant, payload


def test_current_connector_failure_is_not_hidden_by_unit_preflight(monkeypatch):
    from zebra_agent_api import host_manifest_freeze, session_binding

    monkeypatch.setattr(CoverageHttpAdmission, "preflight", lambda self: None)
    monkeypatch.setattr(session_binding, "_frozen_manifest_digest", lambda *args: "0" * 64)

    def unavailable(*args):
        raise host_manifest_freeze.HostManifestFreezeError("private connector unavailable")

    monkeypatch.setattr(host_manifest_freeze, "resolve_admission_profile", unavailable)
    verified = grant()
    result = composed_app().create_session(
        payload(), idempotency_key="key",
        host_context=verified.context, verified_host_grant=verified
    )
    assert result.status_code == 503
    assert result.body == {"status": "host_connector_unavailable"}
