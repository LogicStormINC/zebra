from __future__ import annotations

from struct import unpack

from agent_core.domain.image_attachments import SUPPORTED_IMAGE_MEDIA_TYPES

MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_IMAGE_TOTAL_BYTES = 32 * 1024 * 1024
MAX_IMAGE_EDGE = 8192
MAX_IMAGE_PIXELS = 36_000_000


def inspect_image(payload: bytes, declared_media_type: str) -> tuple[int, int]:
    detected, width, height = _image_header(payload)
    if detected != declared_media_type:
        raise ValueError("image attachment media_type does not match its content")
    if width > MAX_IMAGE_EDGE or height > MAX_IMAGE_EDGE:
        raise ValueError(f"image attachment edge exceeds {MAX_IMAGE_EDGE} pixels")
    if width * height > MAX_IMAGE_PIXELS:
        raise ValueError(f"image attachment exceeds {MAX_IMAGE_PIXELS} decoded pixels")
    return width, height


def is_image_media_type(media_type: str) -> bool:
    return media_type in SUPPORTED_IMAGE_MEDIA_TYPES


def _image_header(payload: bytes) -> tuple[str, int, int]:
    if (
        payload.startswith(b"\x89PNG\r\n\x1a\n")
        and len(payload) >= 45
        and payload[-12:-8] == b"\x00\x00\x00\x00"
        and payload[-8:-4] == b"IEND"
    ):
        width, height = unpack(">II", payload[16:24])
        return "image/png", width, height
    if payload[:6] in {b"GIF87a", b"GIF89a"} and len(payload) >= 14 and payload[-1] == 0x3B:
        width, height = unpack("<HH", payload[6:10])
        return "image/gif", width, height
    if payload.startswith(b"\xff\xd8") and payload.endswith(b"\xff\xd9"):
        return "image/jpeg", *_jpeg_dimensions(payload)
    if (
        payload.startswith(b"RIFF")
        and payload[8:12] == b"WEBP"
        and len(payload) >= 20
        and int.from_bytes(payload[4:8], "little") + 8 <= len(payload)
    ):
        return "image/webp", *_webp_dimensions(payload)
    raise ValueError("image attachment content is not a supported image")


def _jpeg_dimensions(payload: bytes) -> tuple[int, int]:
    offset = 2
    while offset + 9 < len(payload):
        if payload[offset] != 0xFF:
            offset += 1
            continue
        marker = payload[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(payload):
            break
        length = int.from_bytes(payload[offset : offset + 2], "big")
        if length < 2 or offset + length > len(payload):
            break
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            height = int.from_bytes(payload[offset + 3 : offset + 5], "big")
            width = int.from_bytes(payload[offset + 5 : offset + 7], "big")
            return width, height
        offset += length
    raise ValueError("JPEG attachment does not contain valid dimensions")


def _webp_dimensions(payload: bytes) -> tuple[int, int]:
    chunk = payload[12:16]
    data = payload[20:]
    if chunk == b"VP8X" and len(data) >= 10:
        return 1 + int.from_bytes(data[4:7], "little"), 1 + int.from_bytes(data[7:10], "little")
    if chunk == b"VP8L" and len(data) >= 5 and data[0] == 0x2F:
        bits = int.from_bytes(data[1:5], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8 " and len(data) >= 10 and data[3:6] == b"\x9d\x01\x2a":
        return int.from_bytes(data[6:8], "little") & 0x3FFF, int.from_bytes(
            data[8:10], "little"
        ) & 0x3FFF
    raise ValueError("WebP attachment does not contain valid dimensions")
