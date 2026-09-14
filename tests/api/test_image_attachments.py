from __future__ import annotations

from base64 import b64decode, b64encode

from agent_core.domain.image_attachments import ImageAttachmentInput
from zebra_agent_api.session_attachment_inputs import parse_attachment_inputs
from zebra_agent_api.session_payloads import parse_append_session_message_payload


def _png() -> bytes:
    return b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )


def _attachment(payload: bytes | None = None) -> dict[str, str]:
    return {
        "file_name": "chart.png",
        "media_type": "image/png",
        "content_base64": b64encode(payload or _png()).decode("ascii"),
    }


def test_image_attachment_is_validated_as_binary_input() -> None:
    attachments = parse_attachment_inputs([_attachment()])

    assert len(attachments) == 1
    image = attachments[0]
    assert isinstance(image, ImageAttachmentInput)
    assert (image.width, image.height) == (1, 1)
    assert image.payload.startswith(b"\x89PNG")


def test_image_attachment_rejects_declared_type_mismatch() -> None:
    value = _attachment()
    value["media_type"] = "image/jpeg"

    try:
        parse_attachment_inputs([value])
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("mismatched image type was accepted")


def test_image_attachment_rejects_pro_profile_before_admission() -> None:
    response = parse_append_session_message_payload(
        {
            "content": "分析图片",
            "attachments": [_attachment()],
            "model_profile": "deepseek-v4-pro-executor-v1",
        }
    )

    assert response.status_code == 400
    assert "V4.1 Flash" in str(response.body)
