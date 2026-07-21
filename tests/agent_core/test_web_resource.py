from __future__ import annotations

import pytest
from agent_core.domain.web_resource import WebResourceId, WebResourceIdError


def test_new_resource_id_is_valid_and_sortable_prefixed() -> None:
    first = WebResourceId.new()
    second = WebResourceId.new()

    assert str(first).startswith("web_")
    assert first != second
    # round-trips through parse
    assert WebResourceId.parse(str(first)) == first


@pytest.mark.parametrize(
    "value",
    (
        "",
        "web_",
        "web_short",
        "web_WITH-UPPER",
        "web_0123456789abcdefghjkmnpqrstvwxyz!?",  # punctuation
        "fetch_0123456789abcdefghjkmnpqrstvw",  # wrong prefix
    ),
)
def test_parse_rejects_malformed_ids(value: str) -> None:
    with pytest.raises(WebResourceIdError):
        WebResourceId.parse(value)


def test_parse_rejects_non_string() -> None:
    with pytest.raises(WebResourceIdError):
        WebResourceId.parse(123)  # type: ignore[arg-type]
