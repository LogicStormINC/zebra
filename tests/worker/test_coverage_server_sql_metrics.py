"""The SQL observer cannot silently lose nested work or reset counters."""

import pytest

from tests.worker.coverage_server_sql_metrics import difference


def row(calls, *, top=True):
    return {"query": "select controlled", "toplevel": top, "calls": calls,
            "total_exec_time": calls * 2, "rows": calls,
            "shared_blks_hit": calls, "shared_blks_read": 0,
            "blk_read_time": 0, "blk_write_time": 0}


def test_counts_nested_work_separately_and_no_monitoring_is_explicit():
    before = {(1, True): row(3)}, {"stats_reset": 1, "dealloc": 0}
    after = {(1, True): row(5), (2, False): row(4, top=False)}, before[1]
    result = difference(before, after)
    assert result["calls"] == 6
    assert result["top_level_calls"] == 2 and result["nested_calls"] == 4
    assert result["nested_times_are_not_additive"] is True
    assert difference(None, None)["available"] is False


@pytest.mark.parametrize("damage", ["reset", "eviction", "missing", "decrease"])
def test_resets_evictions_disappearances_and_decreases_are_not_savings(damage):
    before = {(1, True): row(3)}, {"stats_reset": 1, "dealloc": 0}
    current, stamp = {(1, True): row(5)}, dict(before[1])
    if damage == "reset":
        stamp["stats_reset"] = 2
    elif damage == "eviction":
        stamp["dealloc"] = 1
    elif damage == "missing":
        current.clear()
    else:
        current[(1, True)] = row(2)
    with pytest.raises(AssertionError, match="measurement"):
        difference(before, (current, stamp))
