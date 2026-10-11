"""Pinned delta keysets stop on short pages, including a later unrelated tail."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agent_storage.postgres.coverage_model_replay_rows import indexed_calls, model_rows


@pytest.mark.parametrize("count", [3, 101])
@pytest.mark.parametrize("selected", [False, True])
def test_model_pages_do_not_probe_beyond_exhaustive_short_page(count, selected):
    connection = Mock()
    rows = [{"sequence": number, "event_type": "coverage_model_call_reserved"}
            for number in range(1, count + 1)]
    upper = Mock()
    upper.fetchone.return_value = {"last": 999}
    pages = []
    for start in range(0, count, 100):
        page = Mock()
        page.fetchall.return_value = rows[start:start + 100]
        pages.append(page)
    connection.execute.side_effect = [upper, *pages]
    binding = SimpleNamespace(session_id="session", namespace="tenant", run_id="run")
    assert list(model_rows(
        connection, "deployment", binding, ("type",),
        record_ids=["record"] if selected else None,
    )) == rows
    assert connection.execute.call_count == 1 + len(pages)


@pytest.mark.parametrize("count", [3, 101])
def test_call_pages_do_not_probe_after_short_page(count):
    connection = Mock()
    rows = [{"reservation_key": f"key{number:03}"} for number in range(count)]
    pages = []
    for start in range(0, count, 100):
        page = Mock()
        page.fetchall.return_value = rows[start:start + 100]
        pages.append(page)
    connection.execute.side_effect = pages
    binding = SimpleNamespace(namespace="tenant", run_id="run")
    assert list(indexed_calls(connection, "deployment", binding, record_ids=["record"])) == rows
    assert connection.execute.call_count == len(pages)
