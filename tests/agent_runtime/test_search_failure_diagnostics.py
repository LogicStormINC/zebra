import json

import pytest
from agent_core.domain.web import parse_web_target
from agent_core.harness.tool_recovery import normalize_failure
from agent_runtime.search_providers import SearXNGSearchProvider
from agent_runtime.web_search import _normalize_response
from agent_tools.search_pipeline import SearchPipeline, SearchPipelineTool, SearchProviderRegistry
from agent_tools.web_search import WebSearchRequest, WebSearchTool

from tests.agent_tools.test_web_search import _tool_call


@pytest.mark.parametrize("v2", [False, True])
@pytest.mark.parametrize(
    "failure,retryable", [("CAPTCHA", False), ("timeout", True), ("access denied", False)]
)
def test_engine_failure_reports_known_execution_and_sanitized_reason(v2, failure, retryable):
    payload = {"results": [], "unresponsive_engines": [["duckduckgo", failure]]}
    if v2:
        provider = SearXNGSearchProvider(
            endpoint="https://search.example/search", fetch_json=lambda url: payload
        )
        registry = SearchProviderRegistry()
        registry.register(provider, default=True)
        tool = SearchPipelineTool(SearchPipeline(registry))
    else:

        class Transport:
            def execute(self, request):
                body = json.dumps(payload).encode()
                return _normalize_response(body, request, len(body))

        tool = WebSearchTool(parse_web_target("https://search.example/search"), Transport())
    result = normalize_failure(tool.handle(_tool_call({"query": "OpenAI news"})), read_only=True)
    assert result.status.value == "failed"
    assert result.metadata["execution_state"] == "executed"
    assert result.metadata["retryable"] is retryable
    assert result.metadata["engine_failures"][0]["engine"] == "duckduckgo"
    assert result.metadata["candidate_count"] == 0
    assert "duckduckgo" in result.metadata["detail"]
    assert "evidence_refs" not in result.metadata


def test_partial_engine_results_do_not_become_fully_certified_success():
    body = json.dumps(
        {
            "results": [{"url": "https://openai.com/news/"}],
            "unresponsive_engines": [["other", "timeout"]],
        }
    ).encode()
    from agent_tools.web_gateway import WebGatewayError

    with pytest.raises(WebGatewayError) as error:
        _normalize_response(
            body,
            WebSearchRequest(
                "call", parse_web_target("https://search.example/search"), "OpenAI", 5
            ),
            len(body),
        )
    assert error.value.metadata["candidate_count"] == 1
    assert error.value.metadata["source_complete"] is False


def test_failure_diagnostics_are_bounded_and_do_not_echo_provider_secrets():
    from agent_runtime.search_health import require_complete_search
    from agent_tools.web_gateway import WebGatewayError

    with pytest.raises(WebGatewayError) as error:
        require_complete_search(
            {
                "results": [],
                "error": "Bearer SECRET_DO_NOT_ECHO",
                "unresponsive_engines": [["bing", "https://upstream.test?api_key=SECRET"]] * 50,
            }
        )
    assert len(error.value.metadata["engine_failures"]) == 8
    assert "SECRET" not in str(error.value)
    assert "SECRET" not in json.dumps(error.value.metadata)
    assert error.value.metadata["retryable"] is False


def test_operator_probe_requires_candidates_not_just_success_status(monkeypatch):
    import runpy
    from pathlib import Path

    probe = runpy.run_path(str(Path(__file__).resolve().parents[2] / "docker/web-search/verify.py"))
    from agent_tools.web_search import WebSearchResponse
    from zebra_agent_config import load_settings

    monkeypatch.setattr("sys.argv", ["verify.py", "--query", "OpenAI news"])
    monkeypatch.setattr(
        "zebra_agent_config.load_settings",
        lambda: load_settings(env={"ZEBRA_WEB_SEARCH_ENDPOINT": "https://search.example/search"}),
    )
    monkeypatch.setattr(
        "agent_runtime.web_search.LocalWebSearchTransport.execute",
        lambda *a: WebSearchResponse((), "searxng", 15, {}),
    )
    assert probe["main"]() == 1


def test_operator_probe_qualifies_collected_search_refs(monkeypatch):
    import runpy
    from pathlib import Path

    from agent_tools.web_search import WebSearchResponse, WebSearchResult
    from zebra_agent_config import load_settings

    probe = runpy.run_path(str(Path(__file__).resolve().parents[2] / "docker/web-search/verify.py"))
    monkeypatch.setattr("sys.argv", ["verify.py", "--query", "OpenAI news"])
    monkeypatch.setattr(
        "zebra_agent_config.load_settings",
        lambda: load_settings(env={"ZEBRA_WEB_SEARCH_ENDPOINT": "https://search.example/search"}),
    )
    monkeypatch.setattr(
        "agent_runtime.web_search.LocalWebSearchTransport.execute",
        lambda *a: WebSearchResponse(
            (WebSearchResult("OpenAI", "https://openai.com/news/", "News"),), "searxng", 150, {}
        ),
    )
    assert probe["main"]() == 0


@pytest.mark.parametrize("operation", ["search", "search_json"])
def test_actual_native_search_paths_preserve_engine_failure_receipt(
    tmp_path, monkeypatch, operation
):
    from dataclasses import asdict

    from agent_runtime.web_gateway import _native_network_call
    from agent_tools.web_gateway import WebGatewayError

    from tests.agent_runtime.test_crawl_source_http import native_tls_source
    from tests.agent_runtime.test_native_network_cancellation import native_connect_proxy

    with native_connect_proxy(monkeypatch) as target:
        with native_tls_source(tmp_path, monkeypatch, "engine_failure", on_listen=target.append):
            endpoint = "https://source.example/search"
            arguments = (
                asdict(WebSearchRequest("call", parse_web_target(endpoint), "OpenAI", 5))
                if operation == "search"
                else endpoint + "?q=OpenAI&format=json"
            )
            with pytest.raises(WebGatewayError) as error:
                payload = _native_network_call(
                    operation, arguments, lambda: None, timeout=5, use_system_proxy=True
                )
                if operation == "search_json":
                    # V2's raw JSON child returns bytes-as-JSON; engine assessment
                    # is deliberately performed by its parent provider.
                    from agent_runtime.search_health import require_complete_search

                    require_complete_search(payload)
            assert error.value.metadata["engine_failures"] == [
                {"engine": "engine", "code": "timeout"}
            ]
            assert error.value.metadata["execution_state"] == "executed"
            assert error.value.metadata["retryable"] is True


def test_operator_probe_uses_the_configured_v2_pipeline(monkeypatch):
    import runpy
    from pathlib import Path

    from agent_tools.search_pipeline import SearchHit
    from zebra_agent_config import load_settings

    probe = runpy.run_path(str(Path(__file__).resolve().parents[2] / "docker/web-search/verify.py"))
    monkeypatch.setattr("sys.argv", ["verify.py", "--query", "OpenAI news"])
    monkeypatch.setattr(
        "zebra_agent_config.load_settings",
        lambda: load_settings(
            env={
                "ZEBRA_WEB_SEARCH_ENDPOINT": "https://search.example/search",
                "ZEBRA_WEB_PIPELINE_V2": "true",
            }
        ),
    )
    monkeypatch.setattr(
        "agent_runtime.search_providers.SearXNGSearchProvider.search",
        lambda *a, **kw: (SearchHit("OpenAI", "https://openai.com/news/", "News"),),
    )
    monkeypatch.setattr(
        "agent_runtime.web_search.LocalWebSearchTransport.execute",
        lambda *a: pytest.fail("V2 probe must not qualify a different legacy pipeline"),
    )
    assert probe["main"]() == 0
