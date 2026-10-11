"""Transport contracts only: fake checks never count as real scratch preflight."""

import io
import json
from uuid import uuid4

import joint_guard_rpc
import pytest


def line(**changes: object) -> bytes:
    return (
        json.dumps({"request_id": str(uuid4()), "op": "guard", "remaining_ms": 1000, **changes})
        + "\n"
    ).encode()


def test_every_request_executes_fresh_check_and_does_not_echo_private_output(capsys):
    calls = []

    def check(remaining: float) -> int:
        calls.append(remaining)
        print("PRIVATE-DO-NOT-EXPORT")
        return 0 if len(calls) == 1 else 2

    output = io.StringIO()
    assert joint_guard_rpc.serve(io.BytesIO(line() + line(remaining_ms=20)), output, check) == 0
    assert calls == [1000, 20]
    values = [json.loads(raw) for raw in output.getvalue().splitlines()]
    assert [v["status"] for v in values] == ["passed", "denied"]
    assert all(set(v) == {"request_id", "status"} for v in values)
    assert "PRIVATE" not in output.getvalue() + capsys.readouterr().out


@pytest.mark.parametrize(
    "raw",
    [
        b"x" * 4097,
        b"{}",
        line(op="cached_guard"),
        line(remaining_ms=0),
        line(remaining_ms=30001),
        line(remaining_ms=True),
        line(remaining_ms=float("nan")),
        line(request_id="private"),
        line(extra="private"),
    ],
)
def test_invalid_protocol_never_checks_or_outputs_identity(raw):
    output = io.StringIO()
    assert (
        joint_guard_rpc.serve(io.BytesIO(raw), output, lambda _: pytest.fail("not admitted")) == 2
    )
    assert output.getvalue() == ""


def test_exception_is_sanitized_and_fail_closed():
    def check(_: float) -> int:
        raise RuntimeError("PRIVATE-config")

    output = io.StringIO()
    assert joint_guard_rpc.serve(io.BytesIO(line()), output, check) == 0
    assert json.loads(output.getvalue())["status"] == "denied"
    assert "PRIVATE" not in output.getvalue()


def test_full_guard_reuses_exact_original_entry_without_writes(monkeypatch):
    import joint_acceptance

    calls = []
    inputs = {"private": "not exported"}

    def original(environment, evidence_dir, **options):
        assert environment is inputs
        assert str(evidence_dir) == "."
        assert options == {"preflight_only": True, "guard": True}
        calls.append(options)
        return 0

    monkeypatch.setattr(joint_acceptance, "run_joint", original)
    assert joint_guard_rpc.full_guard(inputs, 1000) == 0
    assert joint_guard_rpc.full_guard(inputs, 1000) == 0
    assert len(calls) == 2
