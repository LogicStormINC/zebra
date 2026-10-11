"""Read-only pending-source rejection regressions, not native/live proof."""

from copy import deepcopy

import pytest
from joint_authority_observation import pending_approval
from support import E2EError
from test_joint_authority_cases import authority_sample


@pytest.mark.parametrize(
    "defect", [None, "duplicate", "fingerprint", "call", "executed", "decision"]
)
def test_pending_identity_requires_exact_unexecuted_undecided_source(defect):
    _, native = authority_sample("approval")
    native["status"] = "waiting_approval"
    native["rows"].pop()  # Observe before the actual approval decision, never fabricate one.
    pending = native["rows"][-1]
    if defect == "duplicate":
        native["rows"].append(deepcopy(pending))
    elif defect == "fingerprint":
        pending["fingerprint"] = "invented"
    elif defect == "call":
        pending["call"] = ""
    elif defect == "executed":
        native["rows"].append({"event_type": "tool_execution_started", "call": pending["call"]})
    elif defect == "decision":
        native["rows"].append({"event_type": "approval_rejected", "call": pending["call"]})
    if defect:
        with pytest.raises(E2EError):
            pending_approval(native)
    else:
        assert pending_approval(native) == {
            "event_id": pending["event_id"],
            "tool_call_id": pending["call"],
            "call_fingerprint": pending["fingerprint"],
        }


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_terminal_is_not_reinterpreted_as_preparing_approval(status):
    with pytest.raises(E2EError, match="no_longer_pending"):
        pending_approval({"status": status, "rows": []})
