from __future__ import annotations

from agent_core.domain.attachments import TextAttachmentInput
from agent_core.domain.image_attachments import ImageAttachmentInput
from zebra_agent_api.responses import ApiResponse, bad_request


def _model_profile(value: object) -> str | None | ApiResponse:
    if value is None:
        return None
    if value not in {
        "deepseek-v4-flash-executor-v1",
        "deepseek-v4-pro-executor-v1",
    }:
        return bad_request("model_profile is not supported")
    return str(value)


def _has_images(
    attachments: tuple[TextAttachmentInput | ImageAttachmentInput, ...],
) -> bool:
    return any(isinstance(attachment, ImageAttachmentInput) for attachment in attachments)


def _reasoning_effort(value: object) -> str | None | ApiResponse:
    if value is None:
        return None
    if value not in {"none", "low", "high", "max"}:
        return bad_request("reasoning_effort is not supported")
    return str(value)
