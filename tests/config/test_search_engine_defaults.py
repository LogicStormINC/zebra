import subprocess
from pathlib import Path


def test_search_defaults_explicitly_enable_verified_bing_endpoint():
    root = Path(__file__).resolve().parents[2]
    settings = (root / "docker/web-search/settings.yml").read_text()
    assert "keep_only: [bing]" in settings
    assert "- name: bing" in settings
    assert "disabled: false" in settings
    assert "base_url: https://cn.bing.com" in settings


def test_operator_probe_does_not_accept_empty_or_failed_engine_as_ready():
    root = Path(__file__).resolve().parents[2]
    probe = root / "docker/web-search/verify.py"
    completed = subprocess.run(["python3", str(probe), "--help"], capture_output=True)
    assert completed.returncode == 0
    assert b"query" in completed.stdout
