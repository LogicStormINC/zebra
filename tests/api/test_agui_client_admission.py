"""Client-owned AG-UI state is schema-bound and redacted before persistence."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from agent_control_plane.agui_client_admission import (
    AgUiClientAdmissionError,
    admit_agui_client_payload,
)
from agent_core.domain.client_capabilities import (
    ClientActionContract,
    ClientActionRisk,
    ClientReadableContract,
    FrontendCapabilityProfileVersion,
)
from zebra_agent_api.ag_ui_command import _admit_client_mounts


def _profile() -> FrontendCapabilityProfileVersion:
    return FrontendCapabilityProfileVersion(
        frontend_app_id="trench-web",
        revision=3,
        readables=(
            ClientReadableContract(
                name="trench.ui.route",
                state_schema={
                    "type": "object",
                    "properties": {
                        "pathname": {"type": "string", "maxLength": 256},
                    },
                    "required": ["pathname"],
                    "additionalProperties": False,
                },
            ),
            ClientReadableContract(name="trench.ui.selection"),
        ),
        actions=(
            ClientActionContract(
                name="trench.ui.timeline.open",
                risk=ClientActionRisk.NAVIGATION,
            ),
        ),
    )


def test_admission_keeps_only_redacted_client_owned_state() -> None:
    admission = admit_agui_client_payload(
        tools=({"name": "trench.ui.timeline.open"},),
        state={
            "trench.ui.route": {
                "pathname": "/dashboard/strategy",
            },
            "trench.ui.selection": {
                "sessionToken": "must-not-persist",
            },
        },
        profile=_profile(),
    )

    assert admission.sanitized_state == {
        "trench.ui.route": {
            "pathname": "/dashboard/strategy",
        },
        "trench.ui.selection": {
            "sessionToken": "__redacted__",
        },
    }
    assert admission.redacted_keys == ("trench.ui.selection.sessionToken",)


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        ({"zebra.authority": {}}, "not published"),
        ({"trench.ui.route": {}}, "missing"),
        ({"trench.ui.route": {"pathname": "/", "extra": True}}, "undeclared"),
    ],
)
def test_admission_rejects_unowned_or_schema_invalid_state(
    state: dict[str, object], reason: str
) -> None:
    with pytest.raises(AgUiClientAdmissionError, match=reason):
        admit_agui_client_payload(tools=(), state=state, profile=_profile())


def test_state_requires_a_published_profile() -> None:
    with pytest.raises(AgUiClientAdmissionError, match="no published frontend profile"):
        admit_agui_client_payload(
            tools=(),
            state={"trench.ui.route": {"pathname": "/"}},
            profile=None,
        )


def test_server_owned_agui_state_without_a_frontend_mount_is_unchanged() -> None:
    command = {
        "input": {
            "state": {"model_profile": "deepseek", "reasoning_effort": "high"},
            "tools": [],
            "forwardedProps": {},
        }
    }
    original = deepcopy(command)
    app = SimpleNamespace(
        client_platform=SimpleNamespace(frontend_capabilities=object())
    )

    assert _admit_client_mounts(app, command, "/agui/commands") is None
    assert command == original


def test_command_uses_the_client_session_pinned_profile_not_latest() -> None:
    pinned = _profile()
    latest = pinned.model_copy(
        update={"revision": 4, "readables": (pinned.readables[0],)}
    )

    class Profiles:
        def get_latest_profile(self, _app_id):
            return latest

        def get_profile_by_digest(self, _app_id, digest):
            return pinned if digest == pinned.profile_digest else None

    class Sessions:
        def get_session(self, _session_id):
            return SimpleNamespace(
                grant=SimpleNamespace(
                    frontend_app_id="trench-web", profile_digest=pinned.profile_digest
                )
            )

    command = {
        "input": {
            "state": {"trench.ui.selection": {"eventId": "event-1"}},
            "tools": [{"name": "trench.ui.timeline.open"}],
            "forwardedProps": {
                "frontendAppId": "trench-web",
                "clientSessionId": "11111111-1111-4111-8111-111111111111",
                "uiRevision": 7,
            },
        }
    }
    app = SimpleNamespace(
        client_platform=SimpleNamespace(
            client_sessions=Sessions(), frontend_capabilities=Profiles()
        )
    )

    assert _admit_client_mounts(app, command, "/agui/commands") is None
    assert command["client"]["profile_digest"] == pinned.profile_digest
    assert command["client"]["state_snapshot"] == {
        "trench.ui.selection": {"eventId": "event-1"}
    }
