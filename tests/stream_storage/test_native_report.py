"""A measured delivery gap must never become a green JUnit dashboard."""

from tests.stream_storage.native_runner import junit_report


def test_delivery_gap_and_incomplete_matrix_are_counted_as_failures():
    case = {
        "reader": "session",
        "hint": "none",
        "scenario": "idle",
        "runs": 1,
        "repeat": 1,
        "total_seconds": 1,
        "conformance_passed": False,
    }
    suite = junit_report([case])
    assert suite.attrib["failures"] == "1" and len(suite.findall(".//failure")) == 1
    interrupted = junit_report([case], "TimeoutError")
    assert interrupted.attrib["tests"] == "2" and interrupted.attrib["failures"] == "2"
    assert len(interrupted.findall(".//failure")) == 2
