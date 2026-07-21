"""Concrete CrawlGateway: composes a FetchProvider with runtime SSRF, clean-content
budget, durable resource storage, and bounded projection (WEB-PIPE-CRAWL-01).

This is the agent-runtime composition layer that turns a swappable fetch backend
(Crawl4AI in-process, or an offline double) into the Zebra-native
``web.fetch``/``web.crawl``/``web.extract`` behavior: validate URL -> fetch ->
budget -> persist (dedup) -> project -> return resource_id.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from agent_core.domain.web import WebTarget, WebTargetError, parse_web_target
from agent_core.domain.web_resource import WebResourceId
from agent_security.ssrf import HostNameResolver, SsrfError, resolve_and_validate
from agent_storage.web_chunker import chunk_clean_text
from agent_storage.web_resource import (
    ResourceStatus,
    SQLiteWebResourceStore,
    StoredWebResource,
    WebResourceStoreAdapter,
    utc_now_iso,
)
from agent_tools.web_crawl import (
    DEFAULT_MAX_CLEAN_CHARS,
    CrawlGatewayPort,
    FetchOutcome,
    FetchProvider,
    FetchProviderError,
    FetchRequest,
    FetchResult,
)
from agent_tools.web_projection import WebProjector


@dataclass(frozen=True)
class CrawlGateway(CrawlGatewayPort):
    provider: FetchProvider
    store: SQLiteWebResourceStore
    projector: WebProjector
    max_clean_chars: int = DEFAULT_MAX_CLEAN_CHARS
    resolver: HostNameResolver | None = None

    def __post_init__(self) -> None:
        if self.max_clean_chars <= 0:
            raise ValueError("max_clean_chars must be positive")

    def fetch(self, request: FetchRequest, *, max_output_tokens: int) -> FetchOutcome:
        try:
            target = parse_web_target(request.url)
        except WebTargetError as exc:
            raise FetchProviderError(str(exc), reason="invalid_web_target") from exc
        # Runtime SSRF: resolve the public hostname and reject private/metadata.
        try:
            resolve_and_validate(target.hostname, resolver=self.resolver)
        except SsrfError as exc:
            raise FetchProviderError(str(exc), reason="ssrf_blocked") from exc
        if not self.provider.available:
            raise FetchProviderError(
                f"fetch provider {self.provider.name} is unavailable",
                reason="provider_unavailable",
            )
        result = self.provider.fetch(request)
        clean = result.clean_markdown or ""
        source_truncated = not result.complete
        if len(clean) > self.max_clean_chars:
            clean = clean[: self.max_clean_chars]
            source_truncated = True
        content_sha = sha256(clean.encode("utf-8")).hexdigest()
        resource_id = self.store.find_by_content_hash(content_sha)
        if resource_id is None:
            resource_id = self._persist(
                target=target,
                clean=clean,
                content_sha=content_sha,
                result=result,
                source_truncated=source_truncated,
            )
        adapter = WebResourceStoreAdapter(self.store)
        if request.question:
            projection = self.projector.find(
                adapter, resource_id, request.question, max_tokens=max_output_tokens
            )
        else:
            projection = self.projector.default_view(
                adapter, resource_id, max_tokens=max_output_tokens
            )
        return FetchOutcome(
            resource_id=resource_id.value,
            title=result.title,
            final_url=result.final_url,
            content=projection.content,
            truncated=projection.truncated or source_truncated,
            truncation_scope=projection.truncation_scope,
            next_cursor=projection.next_cursor,
            provider=self.provider.name,
            degraded=not result.complete,
            metadata={
                "content_sha256": content_sha,
                "clean_chars": len(clean),
                "fetch_mode": result.fetch_mode,
            },
        )

    def _persist(
        self,
        *,
        target: WebTarget,
        clean: str,
        content_sha: str,
        result: FetchResult,
        source_truncated: bool,
    ) -> WebResourceId:
        record = StoredWebResource(
            resource_id=str(WebResourceId.new()),
            requested_url=target.url,
            final_url=result.final_url,
            content_sha256=content_sha,
            created_at=utc_now_iso(),
            fetch_mode=result.fetch_mode,
            resource_status=(
                ResourceStatus.PARTIAL if source_truncated else ResourceStatus.COMPLETE
            ),
            wire_bytes=result.wire_bytes,
            decoded_bytes=max(result.decoded_bytes, len(clean.encode("utf-8"))),
            clean_chars=len(clean),
            title=result.title,
            content_type=result.content_type,
        )
        return self.store.save(
            resource=record,
            chunks=chunk_clean_text(clean),
            clean_text=clean,
            raw_html=result.raw_html,
        )


# ---------------------------------------------------------------------------
# Crawl4AI provider (import-guarded). The real fetch path is exercised only
# when crawl4ai is installed (Setup Phase); offline tests use a double.
# ---------------------------------------------------------------------------


def is_crawl4ai_available() -> bool:
    import importlib

    try:
        importlib.import_module("crawl4ai")
    except ImportError:
        return False
    return True


@dataclass(frozen=True)
class Crawl4AIFetchProvider:
    """In-process Crawl4AI fetch provider.

    ``available`` reflects whether the crawl4ai package is importable.
    ``fetch`` lazily imports crawl4ai; if absent it raises
    ``FetchProviderError(crawl4ai_not_installed)`` rather than implicitly
    installing anything (Setup Phase owns browser binary pinning — WEB-PIPE-OPS-01).
    """

    browser_headless: bool = True

    @property
    def name(self) -> str:
        return "crawl4ai"

    @property
    def available(self) -> bool:
        return is_crawl4ai_available()

    def fetch(self, request: FetchRequest) -> FetchResult:
        if not is_crawl4ai_available():
            raise FetchProviderError(
                "crawl4ai is not installed; run the Web Setup Phase (WEB-PIPE-OPS-01)",
                reason="crawl4ai_not_installed",
            )
        # Lazy import keeps the package optional. The arun() mapping below follows
        # crawl4ai v0.9.x AsyncWebCrawler; verify against the pinned version in the
        # real-backend E2E smoke (WEB-PIPE-E2E-01) before enabling in product config.
        import asyncio

        from crawl4ai import AsyncWebCrawler  # type: ignore[import-not-found]

        async def _run() -> tuple[str, str | None, str | None]:
            async with AsyncWebCrawler(headless=self.browser_headless) as crawler:
                outcome = await crawler.arun(url=request.url)
                markdown = getattr(outcome, "markdown", "") or ""
                metadata = getattr(outcome, "metadata", None)
                title = metadata.get("title") if isinstance(metadata, dict) else None
                html = getattr(outcome, "html", None)
                return markdown, title, html

        markdown, title, html = asyncio.run(_run())

        return FetchResult(
            requested_url=request.url,
            final_url=request.url,
            clean_markdown=markdown,
            fetch_mode="browser",
            complete=True,
            content_type="text/html",
            title=title,
            raw_html=html,
        )
