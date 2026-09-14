from __future__ import annotations

from agent_core.domain.messages import MessageRole, SessionMessage

_SUPPORTED = frozenset({"image/gif", "image/jpeg", "image/png", "image/webp"})


def image_data_urls(message: SessionMessage) -> tuple[str, ...]:
    urls = message.provider_image_data_urls
    if not urls:
        return ()
    if message.role is not MessageRole.USER:
        raise ValueError("model image inputs require a user message")
    if len(urls) > 4 or any(
        not any(url.startswith(f"data:{media_type};base64,") for media_type in _SUPPORTED)
        for url in urls
    ):
        raise ValueError("model image input data URL is invalid")
    return urls


def chat_completions_content(message: SessionMessage) -> str | list[dict[str, object]]:
    urls = image_data_urls(message)
    if not urls:
        return message.content
    content: list[dict[str, object]] = [{"type": "text", "text": message.content}]
    content.extend(
        {"type": "image_url", "image_url": {"url": url, "detail": "auto"}} for url in urls
    )
    return content


def responses_content(message: SessionMessage) -> str | list[dict[str, object]]:
    urls = image_data_urls(message)
    if not urls:
        return message.content
    content: list[dict[str, object]] = [{"type": "input_text", "text": message.content}]
    content.extend({"type": "input_image", "image_url": url, "detail": "auto"} for url in urls)
    return content
