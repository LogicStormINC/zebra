import json
import sys
from pathlib import Path

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
            "--token",
            "operator-token",
        ],
    )

    assert publish_client_profile.main() == 0
    assert [method for method, _ in calls] == ["GET", "GET"]
    assert '"status": "already_published"' in capsys.readouterr().out
