import pytest
from zebra_agent_api.stream_v2_cursor import StreamV2Cursor, StreamV2CursorCodec


def test_scoped_cursor_round_trip_and_tampering():
    codec = StreamV2CursorCodec(b"a" * 32)
    cursor = StreamV2Cursor("scope", "canonical", "generation", "123-0", 4)
    token = codec.encode(cursor)
    assert codec.decode(token, scope="scope") == cursor
    for invalid, scope in (
        (token, "other"),
        (token[:-1] + "!", "scope"),
        ("v2." + "a" * 4096, "scope"),
    ):
        with pytest.raises(ValueError):
            codec.decode(invalid, scope=scope)
    with pytest.raises(ValueError):
        StreamV2CursorCodec(b"short")
    with pytest.raises(ValueError):
        StreamV2Cursor("scope", live_offset=1)
    with pytest.raises(ValueError):
        StreamV2Cursor("scope", generation="x", live_id="1-0", live_offset=True)
