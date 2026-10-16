"""Run with uv run python scripts/check_web_time_evidence.py; no framework/fixtures."""

from agent_runtime.web_content import project_web_text
from agent_tools.output_projection import ToolOutputProjector


def project(html, limit=262_144):
    return project_web_text(html, content_type="text/html", max_output_bytes=limit)


def check():
    for tag in ("time", "relative-time"):
        text, _ = project(
            f'<main>Release <{tag} datetime="2025-05-02T11:20:31Z">02 May</{tag}></main>'
        )
        assert "2025-05-02T11:20:31+00:00" in text, f"{tag}: source year/timezone lost"
        assert "02 May" in text
    text, _ = project('<main><time datetime="2025-05-02">May 2</time></main>')
    assert "2025-05-02" in text and "00:00" not in text, "date-only source gained a time"
    for wrapper in ('div hidden', 'div aria-hidden="true"', "script", "template", "head"):
        tag = wrapper.split()[0]
        text, _ = project(
            f'<{wrapper}><time datetime="2025-05-02">Secret</time></{tag}><p>Visible</p>'
        )
        assert text == "Visible", f"{wrapper}: ignored temporal evidence leaked"
    for invalid in ("LEAK_ATTR", "2025-99-99", "P4D", "11:20", ""):
        text, _ = project(f'<time datetime="{invalid}">Visible</time>')
        assert text == "Visible", "unvalidated attribute became evidence"
    text, _ = project(
        '<header><time datetime="1999-01-01">Navigation</time></header>'
        '<main><time datetime="2025-05-02">Release</time></main>'
    )
    assert "2025-05-02" in text and "1999" not in text and "Navigation" not in text
    output = ToolOutputProjector(lambda *_: "artifact://release.txt").project_text(
        text + "\n" + "Feature " * 9000, artifact_name="release.txt"
    )
    assert "2025-05-02" in output.model_output, "model preview dropped source date"
    for limit in (1, 32, 100):
        text, metadata = project(
            '<main><time datetime="2025-05-02T11:20:31Z">五月二日</time>'
            + "正文" * 100 + "</main>", limit,
        )
        assert len(text.encode()) <= limit and metadata["output_truncated"]
    plain, _ = project_web_text(
        '<time datetime="2025-05-02">May 2</time>',
        content_type="text/plain", max_output_bytes=128,
    )
    assert plain == '<time datetime="2025-05-02">May 2</time>'
    print("temporal evidence, date-only semantics, hidden/main/invalid/byte/preview bounds pass")


if __name__ == "__main__":
    check()
