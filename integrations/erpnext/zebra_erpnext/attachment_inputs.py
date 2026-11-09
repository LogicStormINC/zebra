"""Bounded attachment transport validation and ordered content digests."""

import base64
import binascii
import hashlib
import json
import struct


def _filename(value):
    from zebra_erpnext import resources

    if not isinstance(value, str) or not value.strip():
        resources._reject("附件文件名不能为空")
    value = value.strip()
    if (
        len(value) > 255
        or value in {".", ".."}
        or any(c in value for c in "/\\")
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        resources._reject("附件文件名必须是安全的文件名")
    return value


def _decode(value, limit, *, allow_empty=False):
    from zebra_erpnext import resources

    if (
        not isinstance(value, str)
        or (not value and not allow_empty)
        or len(value) > ((limit + 2) // 3) * 4
    ):
        resources._reject("附件内容为空或超过大小上限")
    try:
        payload = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        resources._reject("附件 Base64 内容无效")
    if (not payload and not allow_empty) or len(payload) > limit:
        resources._reject("附件内容为空或超过大小上限")
    return payload


def _image_dimensions(payload, media_type):
    # Same bounded header contract as deployed native image_attachment_inputs.py;
    # native admission remains authoritative for decoding/model compatibility.
    from zebra_erpnext import resources

    if (
        media_type == "image/png"
        and payload.startswith(b"\x89PNG\r\n\x1a\n")
        and len(payload) >= 45
        and payload[-12:-4] == b"\x00\x00\x00\x00IEND"
    ):
        return struct.unpack(">II", payload[16:24])
    if (
        media_type == "image/gif"
        and payload[:6] in {b"GIF87a", b"GIF89a"}
        and len(payload) >= 14
        and payload[-1] == 0x3B
    ):
        return struct.unpack("<HH", payload[6:10])
    if (
        media_type == "image/jpeg"
        and payload.startswith(b"\xff\xd8")
        and payload.endswith(b"\xff\xd9")
    ):
        offset = 2
        while offset + 9 < len(payload):
            if payload[offset] != 0xFF:
                offset += 1
                continue
            marker = payload[offset + 1]
            offset += 2
            if marker in {0xD8, 0xD9}:
                continue
            length = int.from_bytes(payload[offset : offset + 2], "big")
            if length < 2 or offset + length > len(payload):
                break
            if marker in {
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            }:
                return int.from_bytes(payload[offset + 5 : offset + 7], "big"), int.from_bytes(
                    payload[offset + 3 : offset + 5], "big"
                )
            offset += length
    if (
        media_type == "image/webp"
        and payload.startswith(b"RIFF")
        and payload[8:12] == b"WEBP"
        and len(payload) >= 20
        and int.from_bytes(payload[4:8], "little") + 8 <= len(payload)
    ):
        chunk, data = payload[12:16], payload[20:]
        if chunk == b"VP8X" and len(data) >= 10:
            return 1 + int.from_bytes(data[4:7], "little"), 1 + int.from_bytes(data[7:10], "little")
        if chunk == b"VP8L" and len(data) >= 5 and data[0] == 0x2F:
            bits = int.from_bytes(data[1:5], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if chunk == b"VP8 " and len(data) >= 10 and data[3:6] == b"\x9d\x01\x2a":
            return int.from_bytes(data[6:8], "little") & 0x3FFF, int.from_bytes(
                data[8:10], "little"
            ) & 0x3FFF
    resources._reject("图片内容与声明的类型不匹配")


def validate_attachments(value, model_profile):
    from zebra_erpnext import resources

    if value is None:
        return []
    if isinstance(value, str):
        # Frappe RPC may encode nested parameters as JSON strings.
        if len(value) > 56 * 1024 * 1024:
            resources._reject("附件请求过大")
        try:
            value = json.loads(value)
        except ValueError:
            resources._reject("附件列表无效")
    if not isinstance(value, list) or len(value) > 4:
        resources._reject("每次最多上传 4 个附件")
    result, totals = [], dict(text=0, document=0, image=0)
    for item in value:
        if not isinstance(item, dict) or set(item) != {"file_name", "media_type", "content_base64"}:
            resources._reject("附件字段无效")
        name = resources._filename(item["file_name"])
        media = item["media_type"].strip().lower() if isinstance(item["media_type"], str) else ""
        if media not in (
            resources.TEXT_TYPES | resources.IMAGE_TYPES | resources.DOCUMENT_TYPES.keys()
        ):
            resources._reject("不支持此附件类型")
        category = (
            "image"
            if media in resources.IMAGE_TYPES
            else "document"
            if media in resources.DOCUMENT_TYPES
            else "text"
        )
        if category == "image" and model_profile != "deepseek-v4-flash-executor-v1":
            resources._reject("当前模型不支持图片；请选择 DeepSeek Flash")
        payload = resources._decode(
            item["content_base64"], resources.ATTACHMENT_LIMITS[category + "_file_bytes"]
        )
        totals[category] += len(payload)
        if totals[category] > resources.ATTACHMENT_LIMITS[category + "_total_bytes"]:
            resources._reject("附件总大小超过此类型的上限")
        if category == "text":
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError:
                resources._reject("文本附件必须使用 UTF-8 编码")
            if not text.strip():
                resources._reject("文本附件不能为空")
        elif category == "document":
            if not name.lower().endswith(resources.DOCUMENT_TYPES[media]):
                resources._reject("文档扩展名与类型不匹配")
            # ponytail: native Cloud performs bounded document extraction and its
            # extracted-text total limit; the Host validates transport and type.
            if not payload.startswith(b"%PDF-" if media == "application/pdf" else b"PK\x03\x04"):
                resources._reject("文档内容与声明的类型不匹配")
        else:
            width, height = resources._image_dimensions(payload, media)
            if not (0 < width <= 8192 and 0 < height <= 8192) or width * height > 36000000:
                resources._reject("图片尺寸超过上限")
        result.append(
            dict(
                file_name=name,
                media_type=media,
                content_base64=base64.b64encode(payload).decode("ascii"),
            )
        )
    return result


def attachment_digest(attachments):
    """Bind names, MIME, ordered bytes without retaining another payload copy."""
    coordinates = [
        dict(
            file_name=a["file_name"],
            media_type=a["media_type"],
            sha256=hashlib.sha256(base64.b64decode(a["content_base64"], validate=True)).hexdigest(),
        )
        for a in attachments
    ]
    return hashlib.sha256(
        json.dumps(coordinates, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
