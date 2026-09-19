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
