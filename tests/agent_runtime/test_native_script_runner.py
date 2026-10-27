import json
import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest
from agent_core.domain.native_script import NativeScriptError, parse_native_script
from agent_core.ports.runtime import (
    EffectiveRuntimeAuthority,
    RuntimeCapabilities,
    RuntimeClass,
    RuntimeExecutionResult,
    RuntimeHandle,
    RuntimeLimits,
    RuntimePort,
    SandboxSpec,
)
from agent_runtime.adapters.os_sandbox import OsSandboxRuntime
from agent_runtime.native_script import NativeScriptRunner

ROOT = Path(__file__).resolve().parents[2] / "docs/contracts/native-script-v1"
VECTORS = json.loads((ROOT / "positive-vectors.json").read_text())
PYTHON = str(Path(sys.executable).resolve())


def spec() -> SandboxSpec:
    return SandboxSpec(
        runtime_class=RuntimeClass.OS_SANDBOX,
        image="development-os-sandbox",
        engine="sandbox-exec",
        workspace_root=str(Path(PYTHON).parent.parent),
        workspace_writable=False,
        network_profile="none",
        limits=RuntimeLimits(max_execution_seconds=30, max_output_bytes=32768),
    )


def package(index: int = 0, source: str | None = None, **patch: object):
    from hashlib import sha256

    vector = VECTORS[index]
    source = vector["source"] if source is None else source
    manifest = (
        vector["manifest"]
        | patch
        | {"source_digest": "sha256:" + sha256(source.encode()).hexdigest()}
    )
    script = parse_native_script(json.dumps(manifest).encode(), source.encode())
    request = vector["invocation"] | {"manifest_digest": script.manifest.digest}
    return script, json.dumps(request).encode()


def runtime_mock(current: SandboxSpec):
    runtime = Mock(spec=RuntimePort)
    runtime.inspect_capabilities.return_value = RuntimeCapabilities(
        runtime_class=current.runtime_class,
        available=True,
        engine=current.engine,
    )
    runtime.provision.return_value = RuntimeHandle.create(
        runtime_name=current.runtime_class,
        workspace_root=current.workspace_root,
        authority=EffectiveRuntimeAuthority(
            runtime_class=current.runtime_class,
            engine=current.engine,
            image=None,
            spec_digest=current.digest,
            network_enforcement="os-sandbox-network-deny",
            workspace_writable=False,
        ),
    )
    return runtime


@pytest.mark.skipif(sys.platform != "darwin", reason="actual Seatbelt proof; Linux/gVisor separate")
@pytest.mark.parametrize("index", [0, 1, 2])
def test_actual_sandbox_executes_three_pinned_kinds(index: int) -> None:
    script, request = package(index)
    result = NativeScriptRunner(OsSandboxRuntime(spec()), spec(), python=PYTHON).run(
        script, request
    )
    assert result.observation.status == "succeeded"
    assert result.observation.manifest_digest == VECTORS[index]["manifest_digest"]
    assert result.observation.output_digest == VECTORS[index]["output_digest"]
    assert json.loads(result.output_json) == VECTORS[index]["output"]
    # A verifier's returned boolean remains data; it is not a Coverage certificate.
    assert "certificate" not in result.observation.model_dump()


@pytest.mark.skipif(sys.platform != "darwin", reason="actual Seatbelt proof")
def test_sandbox_denies_workspace_write_and_host_file_read(tmp_path: Path) -> None:
    path = tmp_path / "sentinel"
    path.write_text("owned-secret")
    for operation in (f"open({str(path)!r}, 'w')", f"open({str(path)!r}).read()"):
        script, request = package(
            source="def execute(arguments):\n    "
            + operation
            + "\n    return {'value':'escaped'}\n"
        )
        result = NativeScriptRunner(OsSandboxRuntime(spec()), spec(), python=PYTHON).run(
            script, request
        )
        assert result.observation.reason == "process_failed"
        assert result.output_json is None
        assert path.read_text() == "owned-secret"
        assert "owned-secret" not in result.observation.model_dump_json()


@pytest.mark.skipif(sys.platform != "darwin", reason="actual Seatbelt proof")
def test_sandbox_denies_actual_loopback_network() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        script, request = package(
            source=(
                "def execute(arguments):\n    import socket\n"
                f"    socket.create_connection(('127.0.0.1', {port}), timeout=0.5)\n"
                "    return {'value':'escaped'}\n"
            )
        )
        result = NativeScriptRunner(OsSandboxRuntime(spec()), spec(), python=PYTHON).run(
            script, request
        )
        assert result.observation.reason == "process_failed"
        listener.settimeout(0.05)
        with pytest.raises(TimeoutError):
            listener.accept()


@pytest.mark.skipif(sys.platform != "darwin", reason="actual Seatbelt proof")
def test_actual_timeout_and_printed_protocol_contamination() -> None:
    for source, reason in (
        ("def execute(arguments):\n    import time\n    time.sleep(3)\n", "timeout"),
        (
            "print('unframed output')\ndef execute(arguments):\n    return {'value':'x'}\n",
            "invalid_response",
        ),
        ("def execute(arguments):\n    return {'value':'x'*40000}\n", "output_limit"),
    ):
        script, request = package(source=source, timeout_seconds=1)
        result = NativeScriptRunner(OsSandboxRuntime(spec()), spec(), python=PYTHON).run(
            script, request
        )
        assert result.observation.reason == reason
        assert result.output_json is None


@pytest.mark.parametrize(
    "patch",
    [
        {"runtime_class": RuntimeClass.TRUSTED_LOCAL},
        {"workspace_writable": True},
        {"network_profile": "full-gateway"},
        {"limits": RuntimeLimits(max_execution_seconds=31)},
    ],
)
def test_unsafe_runtime_refused_before_effects(patch: dict) -> None:
    runtime = runtime_mock(spec())
    with pytest.raises(NativeScriptError, match="unsafe_script_runtime"):
        NativeScriptRunner(runtime, replace(spec(), **patch), python=PYTHON)
    runtime.provision.assert_not_called()


def test_rejects_unbound_response_and_releases_slot() -> None:
    script, request = package()
    runtime = runtime_mock(spec())
    runtime.execute.return_value = RuntimeExecutionResult(
        command=(),
        exit_code=0,
        timed_out=False,
        stderr="",
        stdout=json.dumps(
            {
                "abi": script.manifest.abi,
                "invocation_id": "wrong",
                "manifest_digest": script.manifest.digest,
                "output": {"value": "x"},
            }
        ),
    )
    runner = NativeScriptRunner(runtime, spec(), python=PYTHON)
    for _ in range(2):
        result = runner.run(script, request)
        assert result.observation.reason == "invalid_response"
        assert result.output_json is None
    assert runtime.destroy.call_count == 2


@pytest.mark.parametrize(
    "change",
    [
        {"arguments": {"query": True}},
        {"manifest_digest": "sha256:" + "0" * 64},
        {"invocation_id": "not-a-uuid"},
        {"unexpected": "secret"},
    ],
)
def test_bad_invocation_never_provisions(change: dict) -> None:
    script, request = package()
    runtime = runtime_mock(spec())
    with pytest.raises(NativeScriptError, match="invalid_invocation"):
        NativeScriptRunner(runtime, spec(), python=PYTHON).run(
            script,
            json.dumps(json.loads(request) | change).encode(),
        )
    runtime.provision.assert_not_called()


def test_slot_is_held_until_runtime_finishes_and_unavailable_fails_closed() -> None:
    script, request = package()
    runtime = runtime_mock(spec())
    started, finish = Event(), Event()

    def execute(_):
        started.set()
        assert finish.wait(2)
        return RuntimeExecutionResult(
            command=(), exit_code=1, timed_out=False, stdout="", stderr="secret"
        )

    runtime.execute.side_effect = execute
    runner = NativeScriptRunner(runtime, spec(), python=PYTHON)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runner.run, script, request)
        try:
            assert started.wait(1)
            with pytest.raises(NativeScriptError, match="script_runner_busy"):
                runner.run(script, request)
        finally:
            finish.set()
        result = future.result()
    assert "secret" not in result.observation.model_dump_json()
    runtime.inspect_capabilities.return_value = replace(
        runtime.inspect_capabilities.return_value, available=False
    )
    with pytest.raises(NativeScriptError, match="script_runtime_unavailable"):
        runner.run(script, request)
    assert runtime.provision.call_count == 1


def test_runtime_authority_cannot_be_claimed_by_an_unbound_handle() -> None:
    script, request = package()
    runtime = runtime_mock(spec())
    handle = runtime.provision.return_value
    runtime.provision.return_value = replace(handle, authority=None)
    with pytest.raises(NativeScriptError, match="script_runtime_authority_mismatch"):
        NativeScriptRunner(runtime, spec(), python=PYTHON).run(script, request)
    runtime.execute.assert_not_called()
    runtime.destroy.assert_called_once()


def test_oversize_and_duplicate_invocations_are_refused_before_provision() -> None:
    script, request = package()
    runtime = runtime_mock(spec())
    runner = NativeScriptRunner(runtime, spec(), python=PYTHON)
    for raw in (b" " * 16385, request[:-1] + b',"abi":"cloud-agent.native-script/1"}'):
        with pytest.raises(NativeScriptError, match="invalid_invocation"):
            runner.run(script, raw)
    runtime.provision.assert_not_called()


def test_process_exception_cleans_handle_and_releases_local_admission() -> None:
    script, request = package()
    runtime = runtime_mock(spec())
    runtime.execute.side_effect = OSError("controlled startup failure")
    runner = NativeScriptRunner(runtime, spec(), python=PYTHON)
    for _ in range(2):
        with pytest.raises(OSError, match="controlled startup failure"):
            runner.run(script, request)
    assert runtime.destroy.call_count == 2
