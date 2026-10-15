import importlib.util
import subprocess
from pathlib import Path

import pytest

_PROBE = Path(__file__).resolve().parents[2] / "docker/web-search/verify.py"


def _load_probe():
    spec = importlib.util.spec_from_file_location("search_quality_probe", _PROBE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("source", "expected", "matches"),
    [
        ("https://redis.io/", "https://redis.io/blog/redis-8-ga/", False),
        ("https://redis.io/downloads/", "https://redis.io/blog/redis-8-ga/", False),
        ("https://redis.io/blog/redis-8-ga/", "https://redis.io/blog/redis-8-ga/", True),
        ("https://redis.io/blog/redis-8-ga/?ref=search", "https://redis.io/blog/redis-8-ga/", True),
        ("https://redis.io/blog/redis-8-ga", "https://redis.io/blog/redis-8-ga/", True),
        ("https://redis.io/blog/redis-8-ga-evil/", "https://redis.io/blog/redis-8-ga/", False),
        (
            "https://redis.io.evil.example/blog/redis-8-ga/",
            "https://redis.io/blog/redis-8-ga/",
            False,
        ),
        (
            "https://evil.example/?next=https://redis.io/blog/redis-8-ga/",
            "https://redis.io/",
            False,
        ),
        ("http://redis.io/blog/redis-8-ga/", "https://redis.io/blog/redis-8-ga/", False),
        ("https://redis.io/blog/post/", "https://redis.io/blog/", True),
        ("https://redis.io/search?q=other", "https://redis.io/search?q=release", False),
    ],
)
def test_expected_source_matches_origin_and_path_boundary(source, expected, matches):
    assert _load_probe()._matches_source(source, expected) is matches


def test_custom_query_requires_explicit_quality_constraint_before_network_calls():
    result = subprocess.run(
        ["python3", str(_PROBE), "--query", "Redis release"], capture_output=True
    )
    assert result.returncode == 2
    assert b"--expect-source" in result.stderr


def test_transport_only_is_explicit_and_expectation_counts_are_checked():
    help_result = subprocess.run(["python3", str(_PROBE), "--help"], capture_output=True)
    assert b"--transport-only" in help_result.stdout
    mismatch = subprocess.run(
        [
            "python3",
            str(_PROBE),
            "--query",
            "one",
            "--query",
            "two",
            "--expect-source",
            "https://redis.io/",
        ],
        capture_output=True,
    )
    assert mismatch.returncode == 2
    assert b"--expect-source" in mismatch.stderr
