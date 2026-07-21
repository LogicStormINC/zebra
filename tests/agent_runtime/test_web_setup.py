from __future__ import annotations

import pytest
from agent_runtime.crawl_gateway import is_crawl4ai_available
from agent_runtime.web_setup import (
    EXPECTED_CRAWL4AI_VERSION,
    PLACEHOLDER_SHA256,
    check_web_setup_readiness,
    probe_crawl4ai_version,
    web_setup_downloads,
)
from agent_security import SetupDownload


def test_probe_reports_none_when_crawl4ai_absent() -> None:
    if is_crawl4ai_available():
        pytest.skip("crawl4ai is installed in this environment")
    assert probe_crawl4ai_version() is None


def test_readiness_false_until_provisioned() -> None:
    if is_crawl4ai_available():
        pytest.skip("crawl4ai is installed in this environment")
    readiness = check_web_setup_readiness()
    assert readiness.crawl4ai_installed is False
    assert readiness.ready is False


def test_setup_downloads_reject_placeholder_checksums() -> None:
    with pytest.raises(ValueError):
        web_setup_downloads(
            crawl4ai_url="https://pypi.example/crawl4ai.whl",
            crawl4ai_sha256=PLACEHOLDER_SHA256,
            browser_url="https://cdn.example/browser.zip",
            browser_sha256="a" * 64,
        )
    with pytest.raises(ValueError):
        web_setup_downloads(
            crawl4ai_url="https://pypi.example/crawl4ai.whl",
            crawl4ai_sha256="b" * 64,
            browser_url="https://cdn.example/browser.zip",
            browser_sha256=PLACEHOLDER_SHA256,
        )


def test_setup_downlists_build_pinned_manifest() -> None:
    manifest = web_setup_downloads(
        crawl4ai_url="https://pypi.example/crawl4ai.whl",
        crawl4ai_sha256="c" * 64,
        browser_url="https://cdn.example/browser.zip",
        browser_sha256="d" * 64,
    )

    assert len(manifest) == 2
    assert all(isinstance(item, SetupDownload) for item in manifest)
    assert manifest[0].file_name.startswith(f"crawl4ai-{EXPECTED_CRAWL4AI_VERSION}-")
    assert manifest[1].file_name.startswith("playwright-")
