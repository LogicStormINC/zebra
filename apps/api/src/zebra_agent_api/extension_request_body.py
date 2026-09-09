"""Shared bounded JSON decoding for extension mutations."""

import json

from fastapi import Request


class ExtensionBodyTooLarge(ValueError):
    """The streamed body exceeded the extension request limit."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


async def extension_request_body(request: Request) -> object:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 8192:
            raise ExtensionBodyTooLarge()
        body.extend(chunk)
    return json.loads(body, object_pairs_hook=_unique_object)
