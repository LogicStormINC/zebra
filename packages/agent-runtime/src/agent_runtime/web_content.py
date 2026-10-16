from __future__ import annotations

import re
from datetime import date, datetime
from html.parser import HTMLParser

_IGNORED_TAGS = frozenset(
    {"canvas", "head", "iframe", "noscript", "object", "script", "style", "svg", "template"}
)
_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tr",
        "ul",
    }
)
_CELL_TAGS = frozenset({"td", "th"})
_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }
)
_SPACE = re.compile(r"[ \t\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")


class _ReadableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._stack: list[tuple[str, bool]] = []
        self._main_start: tuple[int, int] | None = None
        self._main_parts: list[str] = []

    @property
    def readable_text(self) -> str:
        main = self._main_parts.copy()
        if self._main_start is not None:
            main.extend(self.parts[self._main_start[1] :])
        # ponytail: explicit main landmarks only; unmarked/empty pages keep full text.
        return _normalize_readable_text("".join(main)) or _normalize_readable_text(
            "".join(self.parts)
        )

    @property
    def ignoring(self) -> bool:
        return any(ignored for _, ignored in self._stack)

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        ignored = (
            tag in _IGNORED_TAGS
            or "hidden" in attributes
            or (attributes.get("aria-hidden") or "").strip().lower() == "true"
        )
        parent_ignored = self.ignoring
        if tag not in _VOID_TAGS:
            self._stack.append((tag, ignored))
        if parent_ignored or ignored:
            return
        if self._main_start is None and tag not in _VOID_TAGS and (
            tag == "main" or (attributes.get("role") or "").strip().lower() == "main"
        ):
            self._main_start = (len(self._stack), len(self.parts))
        if tag == "li":
            self.parts.append("\n- ")
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in _CELL_TAGS:
            self.parts.append("\t")
        if tag in {"time", "relative-time"}:
            # ponytail: preserve typed source evidence, not arbitrary HTML attributes.
            for parse in (date.fromisoformat, datetime.fromisoformat):
                try:
                    stamp = parse(attributes.get("datetime") or "")
                except ValueError:
                    continue
                self.parts.append(f" [datetime: {stamp.isoformat()}] ")
                break

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        match = next(
            (
                index
                for index in range(len(self._stack) - 1, -1, -1)
                if self._stack[index][0] == tag
            ),
            None,
        )
        if match is None:
            return
        was_ignoring = self.ignoring
        del self._stack[match:]
        if self._main_start is not None and match < self._main_start[0]:
            self._main_parts.extend(self.parts[self._main_start[1] :])
            self._main_parts.append("\n\n")
            self._main_start = None
        if was_ignoring or self.ignoring:
            return
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in _CELL_TAGS:
            self.parts.append("\t")

    def handle_data(self, data: str) -> None:
        if not self.ignoring:
            self.parts.append(data)


def project_web_text(
    text: str,
    *,
    content_type: str,
    max_output_bytes: int,
) -> tuple[str, dict[str, str | int | bool]]:
    if max_output_bytes <= 0:
        raise ValueError("max_output_bytes must be positive")
    mode = "decoded_text"
    projected = text
    if content_type in {"text/html", "application/xhtml+xml"}:
        parser = _ReadableHtmlParser()
        try:
            parser.feed(text)
            parser.close()
        except (AssertionError, ValueError) as exc:
            raise ValueError("HTML response could not be projected safely") from exc
        projected = parser.readable_text
        if not projected:
            raise ValueError("HTML response has no readable text")
        mode = "html_to_text"
    output, truncated = _truncate_utf8(projected, max_output_bytes=max_output_bytes)
    return output, {
        "content_projection": mode,
        "output_byte_count": len(output.encode("utf-8")),
        "output_truncated": truncated,
    }


def _normalize_readable_text(value: str) -> str:
    lines = (_SPACE.sub(" ", line).strip() for line in value.replace("\r", "\n").split("\n"))
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def _truncate_utf8(value: str, *, max_output_bytes: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_output_bytes:
        return value, False
    marker = b"\n\n[CONTENT TRUNCATED TO THE WEB OUTPUT LIMIT]\n\n"
    if max_output_bytes <= len(marker):
        return encoded[:max_output_bytes].decode("utf-8", errors="ignore"), True
    available = max_output_bytes - len(marker)
    head_bytes = available * 2 // 3
    tail_bytes = available - head_bytes
    head = encoded[:head_bytes].decode("utf-8", errors="ignore")
    tail = encoded[-tail_bytes:].decode("utf-8", errors="ignore")
    return f"{head}{marker.decode()}{tail}", True
