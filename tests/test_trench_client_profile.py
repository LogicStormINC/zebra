import json
import sys
from pathlib import Path

import pytest
from agent_core.domain.client_capabilities import FrontendCapabilityProfileVersion

from scripts import publish_client_profile

PROFILE = Path(__file__).parent / "fixtures" / "trench_frontend_profile.json"


def test_trench_profile_release_is_complete_and_digest_pinned() -> None:
    profile = FrontendCapabilityProfileVersion.model_validate(json.loads(PROFILE.read_text()))

    assert profile.profile_digest == (
        "2be88e94cdc4038df2ea85b7106510e4f1b021b054ef32ddd007ee4f606082c5"
    )
    assert {readable.name for readable in profile.readables} == {
        "trench.ui.active-filters",
        "trench.ui.open-panels",
        "trench.ui.route",
        "trench.ui.selected-entity",
        "trench.ui.selected-event",
        "trench.ui.timeline-range",
    }
    assert {action.name for action in profile.actions} == {
        "trench.ui.entity.select",
        "trench.ui.event.open",
        "trench.ui.evidence-panel.open",
        "trench.ui.filter.apply",
        "trench.ui.report-draft.fill",
        "trench.ui.report-preview.open",
        "trench.ui.timeline.open",
        "trench.ui.timeline.range.set",
    }


def test_profile_release_is_idempotent_for_the_current_binding(monkeypatch, capsys) -> None:
    profile = FrontendCapabilityProfileVersion.model_validate(json.loads(PROFILE.read_text()))
    calls: list[tuple[str, str]] = []

    def request(method, url, headers, body=None, *, allow_not_found=False):
        calls.append((method, url))
        if "/frontend-profiles/" in url:
            return {
                "profile_digest": profile.profile_digest,
                "revision": profile.revision,
            }
        return {
            "binding_revision": 4,
            "profile_digest": profile.profile_digest,
            "revision": profile.revision,
        }

    monkeypatch.setattr(publish_client_profile, "_request", request)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "publish_client_profile.py",
            "--profile",
            str(PROFILE),
            "--host-app-id",
            "trench",
            "--namespace-id",
            "trench",
            "--token",
            "operator-token",
        ],
    )

    assert publish_client_profile.main() == 0
    assert [method for method, _ in calls] == ["GET", "GET"]
    assert '"status": "already_published"' in capsys.readouterr().out


def test_readonly_release_gate_does_not_publish_missing_profile(monkeypatch):
    calls = []

    def request(method, url, *_args, **_kwargs):
        calls.append(method)
        return None

    monkeypatch.setattr(publish_client_profile, "_request", request)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "publish",
            "--profile",
            str(PROFILE),
            "--host-app-id",
            "trench",
            "--namespace-id",
            "trench",
            "--token",
            "operator",
            "--verify-only",
        ],
    )
    with pytest.raises(SystemExit, match="not published"):
        publish_client_profile.main()
    assert calls == ["GET", "GET"]


def test_release_rejects_digest_mutation_before_binding(monkeypatch):
    calls = []

    def request(method, url, *_args, **_kwargs):
        calls.append(method)
        return {"revision": 1, "profile_digest": "a" * 64}

    monkeypatch.setattr(publish_client_profile, "_request", request)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "publish",
            "--profile",
            str(PROFILE),
            "--host-app-id",
            "trench",
            "--namespace-id",
            "trench",
            "--token",
            "operator",
        ],
    )
    with pytest.raises(SystemExit, match="different digest"):
        publish_client_profile.main()
    assert calls == ["GET"]


def test_new_release_uses_versions_endpoint_and_verifies_binding(monkeypatch):
    profile = FrontendCapabilityProfileVersion.model_validate(json.loads(PROFILE.read_text()))
    calls = []
    answers = iter(
        [
            None,
            {"revision": 0},
            {},
            None,
            {"binding_revision": 1},
            {"profile_digest": profile.profile_digest, "revision": profile.revision},
        ]
    )

    def request(method, url, *_args, **_kwargs):
        calls.append((method, url))
        return next(answers)

    monkeypatch.setattr(publish_client_profile, "_request", request)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "publish",
            "--profile",
            str(PROFILE),
            "--host-app-id",
            "trench",
            "--namespace-id",
            "trench",
            "--token",
            "operator",
        ],
    )
    assert publish_client_profile.main() == 0
    assert calls[2][1].endswith("/trench-web/versions")
    assert calls[-1][0] == "GET"


def test_publishing_requires_explicit_product_binding(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["publish", "--profile", str(PROFILE), "--token", "operator"])
    with pytest.raises(SystemExit) as exc:
        publish_client_profile.main()
    assert exc.value.code == 2


def test_profile_validation_requires_no_product_or_backend(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["publish", "--profile", str(PROFILE), "--check-only"])
    assert publish_client_profile.main() == 0
