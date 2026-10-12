"""Native pure preparation is zero SQL; mutated/unknown delegates stay guarded."""
# ruff: noqa: F401,F811

from dataclasses import replace

import psycopg
import pytest
from agent_core.application.coverage_executor import CoverageExecutor
from agent_core.domain.sessions import SessionStatus
from agent_integrations.coverage_snapshot_source import HostCoverageSnapshotSource
from zebra_agent_config.coverage_settings import CoverageWorkSettings
from zebra_agent_worker.coverage_native_executor import NativeCoverageExecutor

from tests.worker.coverage_model_cloud_fixtures import dsn, model_cloud, postgres_dsn
from tests.worker.test_coverage_dispatch import native_handoff, native_worker


def test_generic_executor_preparation_never_skips_custom_authority():
    executor = CoverageExecutor.__new__(CoverageExecutor)

    def refuse():
        raise ValueError("fresh authority refused")

    executor.check_authority = refuse
    with pytest.raises(ValueError, match="fresh authority refused"):
        executor._preparation_boundary()


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
def test_native_executor_only_owns_pure_preparation(native_worker, monkeypatch):
    import zebra_agent_worker.coverage_dispatch as dispatch

    env = native_worker
    env.service._settings = replace(
        env.service._settings, coverage_work=CoverageWorkSettings(max_milliseconds=60000),
    )
    checked = False

    def compose(**kwargs):
        nonlocal checked
        executor = NativeCoverageExecutor(**kwargs)
        assert executor._qualified_preparation()

        def unexpected(*args, **kwargs):
            pytest.fail("pure preparation dispatched SQL or Host I/O")

        with monkeypatch.context() as patch:
            patch.setattr(psycopg.Connection, "execute", unexpected)
            patch.setattr(HostCoverageSnapshotSource, "_get_descriptor", unexpected)
            for _ in range(32):
                executor._preparation_boundary()
            # Certification still receives this full fresh guard, never the
            # pure preparation hook, even in the qualified native composition.
            with pytest.raises(pytest.fail.Exception, match="dispatched SQL"):
                executor._live()
        for target, name in (
            (executor, "read"), (executor, "check_authority"), (executor, "now"),
            (executor.store, "reserve_attempt"), (executor.runner, "run"),
            (executor.runner.model, "_invoke_or_replay"),
            (executor.read.__self__._adapter, "_maximum"),
            (executor.read.__self__._adapter.host, "budget"),
            (executor.read.__self__._adapter.host, "call"),
            (executor.read.__self__._adapter.host, "now"),
            (executor.read.__self__._adapter.host, "monotonic"),
            (executor.read.__self__._adapter.host, "invoke"),
            (executor.read.__self__._adapter.artifacts, "load"),
            (executor.read.__self__._adapter.artifacts, "publish"),
            (executor.read.__self__._adapter.host.invoke.__self__.transport, "request"),
            (executor.artifacts, "inspect_payload"),
            (executor.artifacts, "check_local_authority"),
        ):
            original = getattr(target, name)
            with monkeypatch.context() as patch:
                patch.setattr(target, name, lambda *args, _original=original, **kw:
                              _original(*args, **kw))
                assert not executor._qualified_preparation()
                patch.setattr(psycopg.Connection, "execute", unexpected)
                with pytest.raises(pytest.fail.Exception, match="dispatched SQL"):
                    executor._preparation_boundary()
        class ForeignDefinition:
            def __eq__(self, other):
                pytest.fail("foreign definition equality executed in pure qualification")

        class ForeignHost:
            @property
            def invoke(self):
                pytest.fail("foreign Host property executed during qualification")

        with monkeypatch.context() as patch:
            patch.setattr(executor.read.__self__._adapter, "host", ForeignHost())
            assert not executor._qualified_preparation()
            patch.setattr(psycopg.Connection, "execute", unexpected)
            with pytest.raises(pytest.fail.Exception, match="dispatched SQL"):
                executor._preparation_boundary()

        for target, name, value in (
            (executor.runner.model, "_definition", ForeignDefinition()),
            (executor.runner, "definitions", {"foreign": ForeignDefinition()}),
        ):
            with monkeypatch.context() as patch:
                patch.setattr(target, name, value)
                assert not executor._qualified_preparation()
        classifier = type(executor)._qualified_preparation

        def forged():
            pytest.fail("forged classifier executed")

        with monkeypatch.context() as patch:
            patch.setattr(executor, "_qualified_preparation", forged)
            assert not classifier(executor)
            patch.setattr(psycopg.Connection, "execute", unexpected)
            with pytest.raises(pytest.fail.Exception, match="dispatched SQL"):
                executor._preparation_boundary()
        checked = True
        return executor

    monkeypatch.setattr(dispatch, "NativeCoverageExecutor", compose)
    handoff = native_handoff(env)
    result = env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
    assert checked and result.session.status is SessionStatus.COMPLETED
