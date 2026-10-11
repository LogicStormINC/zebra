"""Optional concrete bind guards are paired and validated before lock I/O."""

from unittest.mock import Mock

import pytest
from agent_storage.postgres.coverage_transactions import lock_run


@pytest.mark.parametrize(
    "revision,digest",
    [
        (None, "a" * 64),
        (0, None),
        (True, "a" * 64),
        (-1, "a" * 64),
        (1.0, "a" * 64),
        ("1", "a" * 64),
        (0, "A" * 64),
        (0, "a" * 63),
        (0, "a" * 64 + "\n"),
        (0, 123),
        (0, "g" * 64),
    ],
)
def test_invalid_or_partial_guards_refused_before_lock_io(revision, digest):
    connection = Mock()
    with pytest.raises(ValueError):
        lock_run(
            connection,
            "deployment",
            Mock(),
            Mock(),
            expected_stream_revision=revision,
            task_binding_digest=digest,
        )
    connection.execute.assert_not_called()
