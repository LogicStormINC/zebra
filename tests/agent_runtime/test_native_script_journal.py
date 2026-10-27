"""Bounded searches must never turn an incomplete journal into a missing receipt."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agent_core.application.native_script import NativeScriptUnavailable
from agent_runtime.native_script_journal import EventScriptJournal


@pytest.mark.parametrize("failure", ["empty", "wrong-watermark", "event-budget", "byte-budget"])
def test_incomplete_stream_search_is_never_a_cache_miss(failure):
    events = Mock()
    events.read_session_highwater.return_value = 99999

    def page(session, after, **kwargs):
        if failure == "empty":
            return SimpleNamespace(events=(), after_sequence=after, highwater=99999)
        rows = tuple(
            SimpleNamespace(event_type=None, sequence=after + n + 1) for n in range(kwargs["limit"])
        )
        return SimpleNamespace(
            events=rows,
            after_sequence=after,
            highwater=0 if failure == "wrong-watermark" else 99999,
            byte_count=1048576 if failure == "byte-budget" else 1,
        )

    events.read_session_event_page.side_effect = page
    journal = EventScriptJournal(events, uuid4(), lambda *args: None, lambda: None)
    with pytest.raises(NativeScriptUnavailable):
        journal.read(str(uuid4()))
    assert events.read_session_event_page.call_count <= 32


def test_zero_event_highwater_is_complete_and_cancel_is_checked():
    events = Mock()
    events.read_session_highwater.return_value = -1
    check = Mock()
    assert EventScriptJournal(events, uuid4(), lambda *a: None, check).read(str(uuid4())) == ()
    assert check.call_count == 2
