"""uv run python scripts/check_web_link_evidence.py; no framework or network."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_core.harness.evidence_ledger import record_tool_evidence
from agent_runtime.crawl_gateway import CrawlGateway
from agent_runtime.fetch_providers import LocalHttpFetchProvider
from agent_runtime.web_content import project_web_text
from agent_runtime.web_gateway import LocalWebGatewayTransport
from agent_storage.web_resource import SQLiteWebResourceStore
from agent_tools.mcp_proxy import JsonValue
from agent_tools.output_projection import ToolOutputProjector
from agent_tools.web_crawl import FetchRequest
from agent_tools.web_gateway import WebGatewayResponse
from agent_tools.web_projection import WebProjector


def project(html: str, limit: int = 65_536) -> tuple[str, dict[str, JsonValue]]:
    return project_web_text(
        html, content_type="text/html", max_output_bytes=limit,
        base_url="https://example.test/docs/page/",
    )


def check() -> None:
    for href, expected in (
        ("/blog/ga/", "https://example.test/blog/ga/"),
        ("../release.html#features", "https://example.test/docs/release.html"),
        ("https://official.test/release?x=1&amp;y=2", "https://official.test/release?x=1&y=2"),
    ):
        text, metadata = project(f'<main><p>See <a href="{href}">release evidence</a>.</p></main>')
        assert expected in text and "release evidence" in text, text
        receipt = ToolResult(
            tool_call_id=new_tool_call_id(), status=ToolCallStatus.EXECUTED,
            output=text, metadata=metadata,
        )
        assert expected in record_tool_evidence({}, receipt)['evidence_refs']
        preview = ToolOutputProjector(lambda *_: "artifact://web.txt").project_text(
            text + "\n" + "Feature " * 9000, artifact_name="web.txt"
        )
        assert expected in preview.model_output
    for href in (
        "javascript:run()", "mailto:a@example.test", "http://official.test/", "#here", "",
        "https://127.0.0.1/", "https://localhost/", "https://a:b@official.test/",
        "https://official.test:8443/", "https://official.test/" + "x" * 2048,
        "https://[malformed/",
    ):
        text, _ = project(f'<p><a href="{href}">Visible label</a></p>')
        assert text == "Visible label", text
    for wrapper in ('div hidden', 'div aria-hidden="true"', 'script', 'template', 'head'):
        tag = wrapper.split()[0]
        text, metadata = project(
            f'<main><{wrapper}><a href="/secret">Hidden</a></{tag}><p>Visible</p></main>'
        )
        assert text == "Visible", (wrapper, text)
        assert not metadata.get('evidence_refs')
    text, _ = project(
        '<header><a href="/outside">Menu</a></header><main>'
        '<nav><a href="/navigation">Nav label</a></nav>'
        '<p>Read <a href="/release">release</a></p></main>'
    )
    assert "outside" not in text and "navigation" not in text and "/release" in text
    text, _ = project('<a href="/empty"> </a><p>Visible</p>')
    assert text == "Visible", text
    text, _ = project('<a href="/real"><span hidden>Secret</span>Visible</a>')
    assert "/real" in text and "Visible" in text and "Secret" not in text
    text, _ = project(
        '<head><base href="https://other.test/"></head>'
        '<p><a href="/release">Source</a></p>'
    )
    assert "https://example.test/release" in text and "other.test" not in text
    for limit in (1, 32, 100):
        text, metadata = project(
            '<main><a href="/release">正文</a>' + "正文" * 100 + '</main>', limit
        )
        assert len(text.encode()) <= limit and metadata['output_truncated']
    html = '<a href="/release">Literal</a>'
    plain, _ = project_web_text(
        html, content_type="text/plain", max_output_bytes=1024,
        base_url="https://example.test/",
    )
    assert plain == html
    text, metadata = project('<p><a href="/release">Release</a></p>')
    with TemporaryDirectory() as tmp, patch.object(
        LocalWebGatewayTransport, 'execute',
        return_value=WebGatewayResponse(text, 200, 'text/html', len(text), metadata),
    ):
        gateway = CrawlGateway(
            provider=LocalHttpFetchProvider(),
            store=SQLiteWebResourceStore(Path(tmp) / 'web.sqlite', Path(tmp) / 'cache'),
            projector=WebProjector(), resolver=lambda _: ('93.184.216.34',),
        )
        outcome = gateway.fetch(
            FetchRequest('https://example.test/docs/page/'), max_output_tokens=8000
        )
        assert 'https://example.test/release' in outcome.metadata.get('evidence_refs', [])
    inventory: dict[str, object] = {}
    for index in range(4):
        source = f"https://www.official.test/source/{index}"
        receipt = ToolResult(
            tool_call_id=new_tool_call_id(), status=ToolCallStatus.EXECUTED,
            metadata={
                "url": source,
                "evidence_refs": [f"https://a.test/link/{index}/{n:03d}" for n in range(128)],
            },
        )
        inventory = record_tool_evidence(inventory, receipt)
        assert source in inventory["evidence_refs"], "fetched source displaced by discovered links"
        assert len(inventory["evidence_refs"]) <= 128
    assert all(
        f"https://www.official.test/source/{i}" in inventory["evidence_refs"] for i in range(4)
    )
    forged = record_tool_evidence(
        {"evidence_source_refs": ["https://unknown.test/not-collected"]},
        ToolResult(tool_call_id=new_tool_call_id(), status=ToolCallStatus.FAILED),
    )
    assert "https://unknown.test/not-collected" not in forged["evidence_refs"]
    print("HTTPS links, byte/preview bounds, native gateway and bounded primary sources pass")


if __name__ == "__main__":
    check()
