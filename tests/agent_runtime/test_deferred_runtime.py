from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from agent_runtime.adapters.local import LocalRuntime
from agent_runtime.deferred import DeferredRuntime


def test_parallel_preparation_and_cleanup_have_one_owner(tmp_path: Path) -> None:
    calls = []
    runtime = LocalRuntime()

    def prepare():
        calls.append("prepare")
        return runtime, runtime.provision(workspace_root=str(tmp_path))

    deferred = DeferredRuntime(prepare, ready=lambda handle: calls.append("persist"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        handles = list(pool.map(lambda _: deferred.ensure_ready(), range(8)))
    assert len({handle.handle_id for handle in handles}) == 1
    assert calls == ["prepare", "persist"]
    deferred.close()
    deferred.close()
    with pytest.raises(RuntimeError, match="closed"):
        deferred.ensure_ready()


def test_unprepared_close_and_failed_preparation_never_retry() -> None:
    calls = []

    def fail():
        calls.append("prepare")
        raise ValueError("unavailable")

    deferred = DeferredRuntime(fail)
    deferred.close()
    assert calls == []
    deferred = DeferredRuntime(fail)
    for _ in range(2):
        with pytest.raises(ValueError, match="unavailable"):
            deferred.ensure_ready()
    assert calls == ["prepare"]


def test_cancellation_after_prepare_destroys_before_ready(tmp_path: Path) -> None:
    class CountingRuntime(LocalRuntime):
        destroyed = 0

        def destroy(self, handle):
            self.destroyed += 1
            super().destroy(handle)

    runtime = CountingRuntime()
    calls = []

    def prepare():
        calls.append("prepare")
        return runtime, runtime.provision(workspace_root=str(tmp_path))

    def check():
        if calls:
            raise RuntimeError("lease lost")

    deferred = DeferredRuntime(prepare, check=check, ready=lambda _: calls.append("persist"))
    with pytest.raises(RuntimeError, match="lease lost"):
        deferred.ensure_ready()
    deferred.close()
    assert calls == ["prepare"]
    assert runtime.destroyed == 1


def test_authority_persistence_failure_destroys_once(tmp_path: Path) -> None:
    class CountingRuntime(LocalRuntime):
        destroyed = 0

        def destroy(self, handle):
            self.destroyed += 1
            super().destroy(handle)

    runtime = CountingRuntime()

    def prepare():
        return runtime, runtime.provision(workspace_root=str(tmp_path))

    def fail(_):
        raise ValueError("authority mismatch")

    deferred = DeferredRuntime(prepare, ready=fail)
    for _ in range(2):
        with pytest.raises(ValueError, match="authority mismatch"):
            deferred.ensure_ready()
    deferred.close()
    assert runtime.destroyed == 1


def test_target_overrides_fail_closed_without_preparation() -> None:
    from agent_core.ports.runtime import RuntimeCapabilityError, RuntimeHandle

    calls = []

    def prepare():
        calls.append("unexpected")
        raise AssertionError("target override must be refused")

    deferred = DeferredRuntime(prepare)
    with pytest.raises(RuntimeCapabilityError, match="overrides"):
        deferred.provision(workspace_root="/another-workspace")
    with pytest.raises(RuntimeCapabilityError, match="session-wide"):
        deferred.destroy_session("another-session")
    with pytest.raises(RuntimeCapabilityError, match="differs"):
        deferred.destroy(RuntimeHandle.create(runtime_name="foreign"))
    assert calls == []
    deferred.close()


def test_cleanup_failure_surfaces_without_destroy_retry(tmp_path: Path) -> None:
    class FailingRuntime(LocalRuntime):
        destroyed = 0

        def destroy(self, handle):
            self.destroyed += 1
            raise OSError("destroy unavailable")

    runtime = FailingRuntime()

    def prepare():
        return runtime, runtime.provision(workspace_root=str(tmp_path))

    def fail(_):
        raise ValueError("persist failed")

    deferred = DeferredRuntime(prepare, ready=fail)
    with pytest.raises(ValueError, match="persist failed"):
        deferred.ensure_ready()
    for _ in range(2):
        with pytest.raises(OSError, match="destroy unavailable"):
            deferred.close()
    assert runtime.destroyed == 1


@pytest.mark.parametrize("closing_stage", ["prepare", "ready", "check"])
def test_reentrant_close_cannot_publish_ready_or_leak(tmp_path: Path, closing_stage: str) -> None:
    class CountingRuntime(LocalRuntime):
        destroyed = 0

        def destroy(self, handle):
            self.destroyed += 1
            super().destroy(handle)

    runtime = CountingRuntime()
    calls = []

    def prepare():
        handle = runtime.provision(workspace_root=str(tmp_path))
        calls.append("prepared")
        if closing_stage == "prepare":
            deferred.close()
        return runtime, handle

    def ready(_):
        calls.append("ready")
        if closing_stage == "ready":
            deferred.close()

    def check():
        if closing_stage == "check" and calls:
            deferred.close()

    deferred = DeferredRuntime(prepare, ready=ready, check=check)
    with pytest.raises(RuntimeError, match="closed"):
        deferred.ensure_ready()
    deferred.close()
    assert runtime.destroyed == 1
    if closing_stage != "ready":
        assert calls == ["prepared"]


def test_suspend_resume_refreshes_owned_handle(tmp_path: Path) -> None:
    runtime = LocalRuntime()

    def prepare():
        return runtime, runtime.provision(workspace_root=str(tmp_path))

    deferred = DeferredRuntime(prepare)
    initial = deferred.ensure_ready()
    suspended = deferred.suspend(initial)
    assert suspended.suspended
    resumed = deferred.resume(suspended)
    assert not resumed.suspended
    assert deferred.ensure_ready() == resumed
    deferred.destroy(resumed)
