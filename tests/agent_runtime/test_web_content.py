import pytest
from agent_runtime.web_content import project_web_text
from agent_tools.output_projection import ToolOutputProjector


def test_html_projection_keeps_readable_order_and_drops_inactive_content() -> None:
    html = """
    <html><head><title>Hidden title</title><style>.x{}</style></head>
    <body><main><h1>Zebra &amp; Agent</h1>
    <script>LEAK_SCRIPT</script><p>First <strong>fact</strong>.</p>
    <div hidden>LEAK_HIDDEN</div><div aria-hidden="true">LEAK_ARIA</div>
    <ul><li>One</li><li>Two</li></ul>
    <table><tr><th>Name</th><td>Value</td></tr></table></main></body></html>
    """

    text, metadata = project_web_text(
        html,
        content_type="text/html",
        max_output_bytes=65_536,
    )

    assert text == "Zebra & Agent\n\nFirst fact.\n\n- One\n\n- Two\n\nName Value"
    assert "LEAK" not in text
    assert metadata == {
        "content_projection": "html_to_text",
        "output_byte_count": len(text.encode()),
        "output_truncated": False,
    }


def test_html_projection_does_not_end_ignored_content_on_mismatched_tag() -> None:
    text, _ = project_web_text(
        "<script>before</div>still hidden</script><p>Visible</p>",
        content_type="application/xhtml+xml",
        max_output_bytes=128,
    )

    assert text == "Visible"


def test_projection_has_deterministic_utf8_head_tail_limit() -> None:
    text, metadata = project_web_text(
        "开" * 100,
        content_type="text/plain",
        max_output_bytes=100,
    )

    assert "[CONTENT TRUNCATED TO THE WEB OUTPUT LIMIT]" in text
    assert len(text.encode()) <= 100
    assert text.startswith("开") and text.endswith("开")
    assert metadata["output_byte_count"] == len(text.encode())
    assert metadata["output_truncated"] is True
    assert metadata["content_projection"] == "decoded_text"


def test_html_projection_rejects_pages_without_readable_text() -> None:
    with pytest.raises(ValueError, match="no readable text"):
        project_web_text(
            "<html><script>only code</script><style>only css</style></html>",
            content_type="text/html",
            max_output_bytes=128,
        )


@pytest.mark.parametrize("landmark", ['main', 'div role="main"'])
def test_main_landmark_keeps_article_date_in_bounded_model_context(landmark: str) -> None:
    tag = landmark.split()[0]
    html = (
        f"<header>{'Menu item ' * 700}</header><{landmark}>"
        "<header><h1>Release news</h1><time>May 01, 2025</time></header>"
        f"<p>{'Release feature ' * 900}</p></{tag}><footer>Site links</footer>"
    )
    text, _ = project_web_text(html, content_type="text/html", max_output_bytes=262_144)
    saved: list[str] = []

    def persist(content: str, name: str) -> str:
        saved.append(content)
        return "artifact://release.txt"

    output = ToolOutputProjector(persist).project_text(text, artifact_name="release.txt")

    assert "May 01, 2025" in output.model_output
    assert "Release news" in output.model_output
    assert "Menu item" not in text and "Site links" not in text
    assert saved == [text]  # Existing artifact path retains the complete extracted main.
    assert output.metadata["output_truncated"] is True


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("<header>Title</header><p>Unmarked body</p>", "Title\n\nUnmarked body"),
        ("<p>Fallback</p><main></main>", "Fallback"),
        ("<p>Fallback</p><main hidden>Secret</main>", "Fallback"),
        ("<main>One</main><aside>Other</aside><main>Two</main>", "One\n\nTwo"),
        ("<main>One<main>Two</main>Three</main>", "One\nTwo\nThree"),
        ("<div role='main'>One<script>secret</div>still hidden</script>Two</div>", "OneTwo"),
        ("<header>Menu</header><main><p>Unclosed body", "Unclosed body"),
        ("<div><main>Body</div><footer>Other</footer>", "Body"),
        ("<div role='MAIN'>Body</div><footer>Other</footer>", "Body"),
    ],
)
def test_main_landmark_fallback_and_parser_boundaries(html: str, expected: str) -> None:
    text, _ = project_web_text(html, content_type="text/html", max_output_bytes=65_536)

    assert text == expected
