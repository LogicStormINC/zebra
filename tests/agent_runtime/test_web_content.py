import pytest
from agent_runtime.web_content import project_web_text


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
