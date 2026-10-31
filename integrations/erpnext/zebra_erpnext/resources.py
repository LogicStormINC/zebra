"""Bounded native attachments and owned Task resources; never proxy arbitrary URLs."""

import base64
import json
import re
from urllib.parse import quote

import frappe

from zebra_erpnext import cloud
from zebra_erpnext.attachment_inputs import _decode as _decode
from zebra_erpnext.attachment_inputs import _filename as _filename
from zebra_erpnext.attachment_inputs import _image_dimensions as _image_dimensions
from zebra_erpnext.attachment_inputs import attachment_digest as attachment_digest
from zebra_erpnext.attachment_inputs import validate_attachments as validate_attachments

MAX_ARTIFACT_BYTES = 20 * 1024 * 1024
TEXT_TYPES = frozenset(
    (
        "application/json",
        "application/xml",
        "application/yaml",
        "text/css",
        "text/csv",
        "text/html",
        "text/javascript",
        "text/markdown",
        "text/plain",
        "text/yaml",
    )
)
DOCUMENT_TYPES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}
IMAGE_TYPES = frozenset(("image/png", "image/jpeg", "image/gif", "image/webp"))
ATTACHMENT_LIMITS = dict(
    max_files=4,
    text_file_bytes=65536,
    text_total_bytes=131072,
    document_file_bytes=4194304,
    document_total_bytes=8388608,
    image_file_bytes=16777216,
    image_total_bytes=33554432,
    image_max_edge=8192,
    image_max_pixels=36000000,
)


def _reject(message):
    frappe.throw(message)


def _id(value):
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", value)
        or value in {".", ".."}
    ):
        _reject("资源标识无效")
    return quote(value, safe="")


def _json(doc, suffix, *, limit=2 * 1024 * 1024, params=None):
    response = cloud.request(
        doc,
        "GET",
        "/tasks/" + _id(doc.task_id) + suffix,
        params=params,
        stream=True,
        raw_response=True,
    )
    try:
        if response.status_code != 200:
            _reject(f"zebra Cloud 资源暂不可用（{response.status_code!s}）")
        payload = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            payload.extend(chunk)
            if len(payload) > limit:
                _reject("zebra Cloud 资源响应超过上限")
        try:
            value = json.loads(payload)
        except (ValueError, UnicodeError):
            _reject("zebra Cloud 资源响应无效")
        if not isinstance(value, dict):
            _reject("zebra Cloud 资源响应无效")
        return value
    finally:
        response.close()


def _envelope(doc):
    return dict(conversation=doc.name, history_scope="active_segment")


def _number(value):
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None


def usage(conversation):
    doc = cloud.owned(conversation)
    value = _json(doc, "/usage") if doc.task_id else {}
    model = value.get("model_usage") or {}
    model = model if isinstance(model, dict) else {}
    allowed = (
        "model_call_count",
        "cache_hit_tokens",
        "cache_miss_tokens",
        "input_tokens",
        "input_token_limit",
    )
    projection = {k: _number(model[k]) for k in allowed if _number(model.get(k)) is not None}
    for key in ("model", "reasoning_effort"):
        if isinstance(model.get(key), str):
            projection[key] = model[key][:200]
    return dict(
        conversation=doc.name,
        history_scope="task",
        model_usage=projection or None,
        **{
            k: _number(value.get(k))
            for k in ("through_sequence", "attachment_count", "attachment_bytes")
        },
    )


def attachments(conversation, cursor=None):
    """Task-wide metadata page; attachment bodies remain inside native storage."""
    doc = cloud.owned(conversation)
    if cursor is not None and (not isinstance(cursor, str) or not 1 <= len(cursor) <= 512):
        _reject("附件分页标识无效")
    params = dict(limit=64, max_bytes=262144)
    if cursor:
        params["cursor"] = cursor
    value = _json(doc, "/attachments", params=params) if doc.task_id else {}
    rows = value.get("attachments", [])
    if not isinstance(rows, list) or len(rows) > 64:
        _reject("附件列表响应无效")
    result = []
    for row in rows:
        if not isinstance(row, dict):
            _reject("附件列表响应无效")
        entry = {}
        for key in (
            "attachment_id",
            "message_event_id",
            "file_name",
            "media_type",
            "original_media_type",
            "extraction_status",
        ):
            if isinstance(row.get(key), str):
                entry[key] = row[key][:255]
        for key in (
            "size_bytes",
            "original_size_bytes",
            "image_width",
            "image_height",
            "page_count",
            "paragraph_count",
            "worksheet_count",
            "cell_count",
            "slide_count",
        ):
            if _number(row.get(key)) is not None:
                entry[key] = row[key]
        result.append(entry)
    next_cursor = value.get("next_cursor")
    if next_cursor is not None and (not isinstance(next_cursor, str) or len(next_cursor) > 512):
        _reject("附件分页响应无效")
    return dict(
        conversation=doc.name,
        history_scope="task",
        attachments=result,
        has_more=value.get("has_more") is True,
        next_cursor=next_cursor,
        **{
            k: _number(value.get(k))
            for k in ("through_sequence", "attachment_count", "attachment_bytes")
        },
    )


def _artifact(value):
    if not isinstance(value, dict):
        _reject("成果资源响应无效")
    artifact_id = value.get("artifact_id")
    _id(artifact_id)
    result = dict(artifact_id=artifact_id)
    for key, limit in (("label", 255), ("kind", 100), ("source", 100), ("preview", 100000)):
        if isinstance(value.get(key), str):
            result[key] = value[key][:limit]
    result["sequence"] = _number(value.get("sequence"))
    for group, fields in {
        "preview_state": ("redacted", "truncated"),
        "access": ("allowed",),
    }.items():
        nested = value.get(group) or {}
        result[group] = {
            k: nested[k] for k in fields if isinstance(nested, dict) and type(nested.get(k)) is bool
        }
    retrieval = value.get("retrieval") or {}
    result["retrieval"] = (
        {"status": str(retrieval.get("status", "unavailable"))[:100]}
        if isinstance(retrieval, dict)
        else {"status": "unavailable"}
    )
    if result["access"].get("allowed") is not True:
        result.pop("preview", None)
    delivery = value.get("delivery") or {}
    result["delivery"] = {}
    if isinstance(delivery, dict):
        name = delivery.get("file_name")
        # Never send filesystem paths or response-header content supplied upstream.
        if (
            isinstance(name, str)
            and len(name) <= 255
            and name not in {".", ".."}
            and not any(c in name for c in "/\\")
            and not any(ord(c) < 32 or ord(c) == 127 for c in name)
        ):
            result["delivery"]["file_name"] = name
        media = delivery.get("mime_type")
        if isinstance(media, str) and re.fullmatch(r"[\w.+-]+/[\w.+-]+", media):
            result["delivery"]["mime_type"] = media
        result["delivery"]["size_bytes"] = _number(delivery.get("size_bytes"))
    return result


def artifacts(conversation, segment_id=None):
    doc = cloud.owned(conversation)
    rows = (
        _json(doc, "/artifacts", params={"segment_id": segment_id} if segment_id else None).get(
            "artifacts", []
        )
        if doc.task_id
        else []
    )
    if not isinstance(rows, list):
        _reject("成果资源列表无效")
    return dict(
        **_envelope(doc), artifacts=[_artifact(row) for row in rows[:200]], has_more=len(rows) > 200
    )


def artifact_detail(conversation, artifact_id, segment_id=None):
    doc = cloud.owned(conversation)
    value = _json(
        doc,
        "/artifacts/" + _id(artifact_id),
        params={"segment_id": segment_id} if segment_id else None,
    )
    artifact = _artifact(value.get("artifact"))
    if artifact["artifact_id"] != artifact_id:
        _reject("成果资源归属不匹配")
    return dict(**_envelope(doc), artifact=artifact)


def artifact_content(conversation, artifact_id, segment_id=None):
    doc = cloud.owned(conversation)
    detail = artifact_detail(conversation, artifact_id, segment_id)["artifact"]
    if detail["access"].get("allowed") is not True:
        _reject("当前会话策略不允许读取此成果资源")
    delivery = detail["delivery"]
    size = delivery.get("size_bytes")
    if type(size) is not int or not 0 <= size <= MAX_ARTIFACT_BYTES:
        _reject("成果资源大小未知或超过 20 MiB 下载上限")
    value = _json(
        doc,
        "/artifacts/" + _id(artifact_id) + "/content",
        limit=((size + 2) // 3) * 4 + 65536,
        params={"segment_id": segment_id} if segment_id else None,
    )
    if (
        value.get("artifact_id") != artifact_id
        or value.get("encoding") != "base64"
        or value.get("status") != "ok"
    ):
        _reject("成果资源内容响应无效")
    payload = _decode(value.get("content_base64"), size, allow_empty=True)
    if len(payload) != size or value.get("size_bytes") != size:
        _reject("成果资源大小校验失败")
    return dict(
        **_envelope(doc),
        artifact_id=artifact_id,
        status="ok",
        encoding="base64",
        content_base64=base64.b64encode(payload).decode("ascii"),
        size_bytes=size,
        file_name=delivery.get("file_name") or artifact_id,
        media_type=delivery.get("mime_type") or "application/octet-stream",
    )


def artifact_download(conversation, artifact_id, segment_id=None):
    return artifact_content(conversation, artifact_id, segment_id)


def preview_mime(name, media):
    safe = {
        "txt": "text/plain",
        "md": "text/markdown",
        "csv": "text/csv",
        "json": "application/json",
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
        "mp4": "video/mp4",
        "webm": "video/webm",
        "ogg": "video/ogg",
    }
    if (
        isinstance(name, str)
        and name.lower().endswith(".json")
        and media in {"application/vnd.vegalite+json", "application/vnd.vegalite.v6+json"}
    ):
        return "application/json"
    return (
        media
        if isinstance(name, str) and safe.get(name.rsplit(".", 1)[-1].lower()) == media
        else None
    )


def segments(conversation, after=-1):
    doc = cloud.owned(conversation)
    from zebra_erpnext import runtime

    if runtime.release(doc) != runtime.FULL:
        return {"segments": [], "has_more": False, "legacy": True}
    try:
        after = int(after)
        if after < -1:
            raise ValueError
    except (TypeError, ValueError):
        _reject("历史分段分页无效")
    if not doc.task_id:
        return {"segments": [], "has_more": False}
    return _json(doc, "/artifact-segments", params={"after": str(after), "limit": "50"})
