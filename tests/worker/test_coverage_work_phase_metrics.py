"""Profiling observes source methods without replacing qualified delegates."""

import sys
from collections import defaultdict
from contextvars import ContextVar

import pytest

from tests.worker.coverage_work_phase_metrics import observe_phases


class NativeProbe:
    def outer(self, phase):
        assert phase.get() == "NativeProbe.outer"
        assert self.inner(phase)
        assert phase.get() == "NativeProbe.outer"
        return False

    def inner(self, phase):
        assert phase.get() == "NativeProbe.inner"
        return True

    def counted(self, phase):
        assert phase.get() == "outside"
        return True


@pytest.mark.parametrize("failure", [False, True])
def test_observer_preserves_delegates_and_restores_phase_and_profiler(failure):
    phase = ContextVar("profile_probe", default="outside")
    cost = defaultdict(lambda: {"calls": 0, "seconds": 0.0})
    outer, inner, previous = NativeProbe.outer, NativeProbe.inner, sys.getprofile()

    def run():
        with observe_phases(
            ((NativeProbe, "outer"), (NativeProbe, "inner")), phase, cost,
            counts_only=((NativeProbe, "counted"),),
        ):
            assert NativeProbe.outer is outer and NativeProbe.inner is inner
            assert not NativeProbe().outer(phase)
            assert NativeProbe().counted(phase)
            if failure:
                raise ValueError("probe failure")

    if failure:
        with pytest.raises(ValueError, match="probe failure"):
            run()
    else:
        run()
    assert sys.getprofile() is previous and phase.get() == "outside"
    assert NativeProbe.outer is outer and NativeProbe.inner is inner
    assert cost["NativeProbe.outer"]["calls"] == cost["NativeProbe.inner"]["calls"] == 1
    assert cost["NativeProbe.outer"]["false_results"] == 1
    assert cost["NativeProbe.inner"]["true_results"] == 1
    assert cost["NativeProbe.counted"]["calls"] == 1
