import pytest
from agent_core.harness.quality_gates import _unsupported_urls

SOURCE = "https://www.itjuzi.com/api/telegraph.xml"


@pytest.mark.parametrize("marker", ["`", "``", "```"])
def test_code_delimiter_is_not_part_of_collected_url(marker):
    assert _unsupported_urls(f"{marker}{SOURCE}{marker}、深交所创业板", (SOURCE,)) == ()


def test_code_delimiter_does_not_authorize_uncollected_url():
    invented = SOURCE + "/invented"
    assert _unsupported_urls(f"`{invented}`、说明", (SOURCE,)) == (invented,)


def test_annotation_extended_url_still_fails():
    assert _unsupported_urls(f"[原文]({SOURCE}（说明）)", (SOURCE,))
