"""Native v2 web tool wiring for the local tool gateway (WEB-PIPE integration).

Builds the durable resource store, the swappable fetch provider (Crawl4AI when
provisioned, else local HTTP), the CrawlGateway, and registers the native
``web.fetch``/``web.crawl``/``web.extract``/``web.read``/``web.find`` tools plus
the rebuilt ``web.search`` pipeline. Kept in its own module so the harness stays
under the file-size gate.
"""

from __future__ import annotations

from pathlib import Path

from agent_core.domain.web import WebTarget
from agent_storage.web_resource import SQLiteWebResourceStore, WebResourceStoreAdapter
from agent_tools import ToolRegistry
from agent_tools.search_pipeline import (
    SearchPipeline,
    SearchPipelineTool,
    SearchProviderRegistry,
)
from agent_tools.web_crawl import (
    DEFAULT_FETCH_OUTPUT_TOKENS,
    FetchProviderError,
    FetchRequest,
    WebCrawlTool,
    WebExtractTool,
    WebFetchV2Tool,
)
from agent_tools.web_projection import WebFindTool, WebProjector, WebReadTool

from agent_runtime.crawl_gateway import Crawl4AIFetchProvider, CrawlGateway, is_crawl4ai_available
from agent_runtime.fetch_providers import LocalHttpFetchProvider
from agent_runtime.search_providers import SearXNGSearchProvider


def register_native_web_tools(
    registry: ToolRegistry,
    *,
    enabled_names: frozenset[str],
    workspace_root: Path,
    search_endpoint: WebTarget | None,
    trusted_local: bool,
) -> None:
    web_store = SQLiteWebResourceStore(
        workspace_root / ".zebra-agent" / "web_resources.sqlite",
        workspace_root / ".zebra-agent" / "web_cache",
    )
    web_adapter = WebResourceStoreAdapter(web_store)
    web_projector = WebProjector()
    fetch_provider = (
        Crawl4AIFetchProvider()
        if is_crawl4ai_available()
        else LocalHttpFetchProvider(use_system_proxy=trusted_local)
    )
    crawl_gateway = CrawlGateway(
        provider=fetch_provider, store=web_store, projector=web_projector
    )
    for web_tool in (
        WebFetchV2Tool(gateway=crawl_gateway),
        WebCrawlTool(gateway=crawl_gateway),
        WebExtractTool(gateway=crawl_gateway),
        WebReadTool(store=web_adapter, projector=web_projector),
        WebFindTool(store=web_adapter, projector=web_projector),
    ):
        if web_tool.contract.name in enabled_names:
            registry.register(web_tool.contract, web_tool.handle)
    if search_endpoint is not None and "web.search" in enabled_names:
        search_registry = SearchProviderRegistry()
        search_registry.register(
            SearXNGSearchProvider(
                endpoint=search_endpoint.url, use_system_proxy=trusted_local
            ),
            default=True,
        )

        def _search_fetch(url: str) -> str | None:
            try:
                outcome = crawl_gateway.fetch(
                    FetchRequest(url=url), max_output_tokens=DEFAULT_FETCH_OUTPUT_TOKENS
                )
            except FetchProviderError:
                return None
            return outcome.content

        search_tool = SearchPipelineTool(
            pipeline=SearchPipeline(
                registry=search_registry,
                fetcher=_search_fetch,
            )
        )
        registry.register(search_tool.contract, search_tool.handle)
