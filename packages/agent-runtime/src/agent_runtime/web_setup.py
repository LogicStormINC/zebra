"""Web Setup Phase (WEB-PIPE-OPS-01).

Crawl4AI and its Playwright browser binaries must be provisioned by the Setup
Phase — pinned version + SHA-256, fetched through the existing
``SetupEgressGateway`` — never implicitly installed on the first tool call
(aligned with WEB-INT-PLAN-01 §3.2). Until Setup provisions them,
``Crawl4AIFetchProvider.available`` is False and ``fetch`` raises
``crawl4ai_not_installed``; this module exposes the readiness probe and the
pinned download manifest operators provision against.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_security import SetupDownload

#: Crawl4AI package version the Setup Phase must provision. Operators pin the
#: exact wheel and supply its SHA-256 via ``web_setup_downloads``; bumping this
#: requires a new setup task + contract regression.
EXPECTED_CRAWL4AI_VERSION = "0.9.0"
DEFAULT_BROWSER = "chromium"

#: Sentinel rejected as a placeholder sha256 — forces operators to fill the real digest.
PLACEHOLDER_SHA256 = "0" * 64


@dataclass(frozen=True)
class WebSetupReadiness:
    crawl4ai_installed: bool
    crawl4ai_version: str | None
    version_matches: bool
    browser_ready: bool

    @property
    def ready(self) -> bool:
        return self.crawl4ai_installed and self.version_matches and self.browser_ready


def probe_crawl4ai_version() -> str | None:
    """Return the installed crawl4ai version, or None if not installed. Never imports
    implicitly elsewhere and never installs."""
    try:
        import crawl4ai  # type: ignore[import-not-found]
    except ImportError:
        return None
    return getattr(crawl4ai, "__version__", None)


def check_web_setup_readiness(
    *,
    expected_version: str = EXPECTED_CRAWL4AI_VERSION,
    browser_ready: bool | None = None,
) -> WebSetupReadiness:
    version = probe_crawl4ai_version()
    installed = version is not None
    if browser_ready is None:
        # Without an explicit probe, browser readiness tracks crawl4ai presence.
        browser_ready = installed
    return WebSetupReadiness(
        crawl4ai_installed=installed,
        crawl4ai_version=version,
        version_matches=version == expected_version,
        browser_ready=browser_ready,
    )


def web_setup_downloads(
    *,
    crawl4ai_url: str,
    crawl4ai_sha256: str,
    browser_url: str,
    browser_sha256: str,
    crawl4ai_version: str = EXPECTED_CRAWL4AI_VERSION,
    browser: str = DEFAULT_BROWSER,
) -> tuple[SetupDownload, ...]:
    """Build the pinned, checksum-verified download manifest for the Setup Phase.

    Both digests are required and must not be placeholders — the whole point is
    that nothing provisions without a verified SHA-256.
    """
    _reject_placeholder(crawl4ai_sha256, "crawl4ai_sha256")
    _reject_placeholder(browser_sha256, "browser_sha256")
    return (
        SetupDownload(
            url=crawl4ai_url,
            file_name=f"crawl4ai-{crawl4ai_version}-py3-none-any.whl",
            sha256=crawl4ai_sha256,
        ),
        SetupDownload(
            url=browser_url,
            file_name=f"playwright-{browser}.zip",
            sha256=browser_sha256,
        ),
    )


def _reject_placeholder(value: str, field_name: str) -> None:
    if value.strip().lower() == PLACEHOLDER_SHA256:
        raise ValueError(f"{field_name} must be a real SHA-256, not the placeholder")
