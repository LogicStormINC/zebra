"""Invalid workload arguments must fail before connecting to native dependencies."""

from unittest.mock import patch

from tests.stream_storage.native_runner import cli


def test_cli_rejects_nonfinite_unbounded_and_duplicate_dimensions():
    with patch(
        "tests.stream_storage.native_runner.main",
        side_effect=AssertionError("invalid arguments reached native workload"),
    ):
        for flag, value in (
            ("--seconds", "nan"),
            ("--seconds", "inf"),
            ("--seconds", "3601"),
            ("--cadence", "nan"),
            ("--cadence", "inf"),
            ("--cadence", "3601"),
            ("--repeats", "11"),
            ("--repeats", "0"),
            ("--sizes", "1,1"),
            ("--readers", "session,session"),
            ("--hints", "live,live"),
            ("--scenarios", "idle,idle"),
        ):
            try:
                cli([flag, value])
            except SystemExit as exc:
                assert exc.code == 2, (flag, value)
            else:
                raise AssertionError(f"unbounded CLI argument accepted: {flag}={value}")
