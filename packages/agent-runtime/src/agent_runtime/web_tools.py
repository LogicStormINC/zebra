"""Native v2 web tool wiring for the local tool gateway (WEB-PIPE integration).

Builds the durable resource store, the swappable fetch provider (Crawl4AI when
provisioned, else local HTTP), the CrawlGateway, and registers the native
``web.fetch``/``web.crawl``/``web.extract``/``web.read``/``web.find`` tools plus
the rebuilt ``web.search`` pipeline. Kept in its own module so the harness stays
under the file-size gate.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import BoundedSemaphore

from agent_core.domain.tools import ToolCall, ToolResult
from agent_core.domain.web import WebTarget, WebTargetError, parse_web_target
from agent_storage.web_resource import SQLiteWebResourceStore, WebResourceStoreAdapter
from agent_tools import ToolRegistry
from agent_tools.search_pipeline import (
    SearchPipeline,
    SearchPipelineTool,
    SearchProviderRegistry,
)
from agent_tools.web_crawl import (
    DEFAULT_FETCH_OUTPUT_TOKENS,
    FetchOutcome,
    FetchProviderError,
    FetchRequest,
    WebCrawlTool,
    WebExtractTool,
    WebFetchV2Tool,
)
from agent_tools.web_gateway import WebFetchTool, WebGatewayTransport
from agent_tools.web_projection import WebFindTool, WebProjector, WebReadTool
from agent_tools.web_search import WebSearchTool, WebSearchTransport

from agent_runtime.crawl_gateway import Crawl4AIFetchProvider, CrawlGateway, is_crawl4ai_available
from agent_runtime.fetch_providers import LocalHttpFetchProvider
from agent_runtime.search_providers import SearXNGSearchProvider
from agent_runtime.web_gateway import LocalWebGatewayTransport
from agent_runtime.web_search import LocalWebSearchTransport


def register_web_tools(
    registry: ToolRegistry,
    *,
    enabled_names: frozenset[str],
    workspace_root: Path,
    web_gateway_transport: WebGatewayTransport | None,
    web_search_endpoint: str | None,
    web_search_transport: WebSearchTransport | None,
    max_output_bytes: int,
    trusted_local: bool,
    web_pipeline_v2: bool,
    network_cancellation_check: Callable[[], None] | None,
    fetch_factory: Callable[..., WebGatewayTransport],
    search_factory: Callable[..., WebSearchTransport],
    web_search_private_backend: bool = False,
) -> frozenset[str]:
    """Register Web handlers and return the audited runtime-free subset."""
    search_endpoint = optional_web_search_endpoint(
        web_search_endpoint, web_pipeline_v2=web_pipeline_v2
    )
    if web_pipeline_v2:
        if web_gateway_transport is not None or web_search_transport is not None:
            raise ValueError(
                "legacy web transports are not supported when web_pipeline_v2 is enabled"
            )
        register_native_web_tools(
            registry,
            enabled_names=enabled_names,
            workspace_root=workspace_root,
            search_endpoint=search_endpoint,
            trusted_local=trusted_local,
            network_cancellation_check=network_cancellation_check,
            trusted_search_endpoint=(
                search_endpoint.url if web_search_private_backend and search_endpoint else None
            ),
        )
        return frozenset()
    # Legacy remains default until v2 replicates durable network authority.
    cancel_options = (
        {"network_cancellation_check": network_cancellation_check}
        if network_cancellation_check is not None
        else {}
    )
    # ponytail: two network handlers per gateway/attempt; fleet-wide admission is separate.
    slots = BoundedSemaphore(2)
    runtime_free: set[str] = set()

    def register(tool: WebFetchTool | WebSearchTool, *, parallel_safe: bool) -> None:
        if not parallel_safe:
            registry.register(tool.contract, tool.handle)
            return

        def handle(call: ToolCall) -> ToolResult:
            with slots:
                return tool.handle(call)

        registry.register(replace(tool.contract, parallel_safe=True), handle)
        # These exact default transports use native egress, never RuntimePort.
        runtime_free.add(tool.contract.name)

    fetch_transport = web_gateway_transport or fetch_factory(
        use_system_proxy=trusted_local, **cancel_options
    )
    if "web.fetch" in enabled_names:
        tool = WebFetchTool(fetch_transport, max_output_bytes=max_output_bytes)
        register(tool, parallel_safe=(
            web_gateway_transport is None and type(fetch_transport) is LocalWebGatewayTransport
        ))
    if search_endpoint is not None and "web.search" in enabled_names:
        search_transport = web_search_transport or search_factory(
            use_system_proxy=trusted_local,
            **cancel_options,
            **(
                {"trusted_search_endpoint": search_endpoint.url}
                if web_search_private_backend
                else {}
            ),
        )
        search = WebSearchTool(endpoint=search_endpoint, transport=search_transport)
        register(search, parallel_safe=(
            web_search_transport is None and type(search_transport) is LocalWebSearchTransport
        ))

    return frozenset(runtime_free)


def optional_web_search_endpoint(
    value: str | None, *, web_pipeline_v2: bool = False
) -> WebTarget | None:
    if value is None:
        return None
    try:
        return parse_web_target(value)
    except WebTargetError as exc:
        if web_pipeline_v2:
            raise ValueError(
                f"web_search_endpoint is not a valid web target for web_pipeline_v2: {exc}"
            ) from exc
        return None


def register_native_web_tools(
    registry: ToolRegistry,
    *,
    enabled_names: frozenset[str],
    workspace_root: Path,
    search_endpoint: WebTarget | None,
    trusted_local: bool,
    network_cancellation_check: Callable[[], None] | None = None,
    trusted_search_endpoint: str | None = None,
) -> None:
    web_store = SQLiteWebResourceStore(
        workspace_root / ".zebra-agent" / "web_resources.sqlite",
        workspace_root / ".zebra-agent" / "web_cache",
    )
    web_adapter = WebResourceStoreAdapter(web_store)
    web_projector = WebProjector()
    fetch_provider = (
        (
            Crawl4AIFetchProvider(network_cancellation_check=network_cancellation_check)
            if network_cancellation_check is not None
            else Crawl4AIFetchProvider()
        )
        if trusted_local and is_crawl4ai_available()
        else LocalHttpFetchProvider(
            use_system_proxy=trusted_local, network_cancellation_check=network_cancellation_check
        )
    )
    crawl_gateway = CrawlGateway(
        provider=fetch_provider,
        store=web_store,
        projector=web_projector,
        network_cancellation_check=network_cancellation_check,
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
                endpoint=search_endpoint.url,
                use_system_proxy=trusted_local,
                network_cancellation_check=network_cancellation_check,
                trusted_search_endpoint=trusted_search_endpoint,
            ),
            default=True,
        )

        def _search_fetch(url: str) -> FetchOutcome | None:
            try:
                outcome = crawl_gateway.fetch(
                    FetchRequest(url=url), max_output_tokens=DEFAULT_FETCH_OUTPUT_TOKENS
                )
            except FetchProviderError:
                return None
            return outcome

        search_tool = SearchPipelineTool(
            pipeline=SearchPipeline(
                registry=search_registry,
                fetcher=_search_fetch,
            )
        )
        registry.register(search_tool.contract, search_tool.handle)
