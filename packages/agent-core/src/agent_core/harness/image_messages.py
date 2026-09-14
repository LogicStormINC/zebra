from __future__ import annotations

from base64 import b64encode
from hashlib import sha256

from agent_core.domain.image_attachments import ImageAttachmentContextInput


def image_data_urls(
    images: tuple[ImageAttachmentContextInput, ...],
) -> tuple[str, ...]:
    urls: list[str] = []
    for image in images:
        if sha256(image.payload).hexdigest() != image.sha256:
            raise ValueError("image attachment digest does not match its payload")
        encoded = b64encode(image.payload).decode("ascii")
        urls.append(f"data:{image.media_type};base64,{encoded}")
    return tuple(urls)
