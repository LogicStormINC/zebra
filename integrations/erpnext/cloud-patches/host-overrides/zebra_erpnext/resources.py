"""Bounded native attachments and owned Task resources; never proxy arbitrary URLs."""
import base64
import binascii
import hashlib
import json
import re
import struct
from urllib.parse import quote

import frappe
from zebra_erpnext import cloud

MAX_ARTIFACT_BYTES = 20 * 1024 * 1024
TEXT_TYPES = frozenset(('application/json', 'application/xml', 'application/yaml',
    'text/css', 'text/csv', 'text/html', 'text/javascript', 'text/markdown', 'text/plain', 'text/yaml'))
DOCUMENT_TYPES = {'application/pdf': '.pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx'}
IMAGE_TYPES = frozenset(('image/png', 'image/jpeg', 'image/gif', 'image/webp'))
ATTACHMENT_LIMITS = dict(max_files=4, text_file_bytes=65536, text_total_bytes=131072,
    document_file_bytes=4194304, document_total_bytes=8388608,
    image_file_bytes=16777216, image_total_bytes=33554432,
    image_max_edge=8192, image_max_pixels=36000000)


def _reject(message):
    frappe.throw(message)


def _filename(value):
    if not isinstance(value, str) or not value.strip():
        _reject('附件文件名不能为空')
    value = value.strip()
    if len(value) > 255 or value in {'.', '..'} or any(c in value for c in '/\\') or any(ord(c) < 32 or ord(c) == 127 for c in value):
        _reject('附件文件名必须是安全的文件名')
    return value


def _decode(value, limit, *, allow_empty=False):
    if not isinstance(value, str) or (not value and not allow_empty) or len(value) > ((limit + 2) // 3) * 4:
        _reject('附件内容为空或超过大小上限')
    try:
        payload = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        _reject('附件 Base64 内容无效')
    if (not payload and not allow_empty) or len(payload) > limit:
        _reject('附件内容为空或超过大小上限')
    return payload


def _image_dimensions(payload, media_type):
    # Same bounded header contract as deployed native image_attachment_inputs.py;
    # native admission remains authoritative for decoding/model compatibility.
    if media_type == 'image/png' and payload.startswith(b'\x89PNG\r\n\x1a\n') and len(payload) >= 45 and payload[-12:-4] == b'\x00\x00\x00\x00IEND':
        return struct.unpack('>II', payload[16:24])
    if media_type == 'image/gif' and payload[:6] in {b'GIF87a', b'GIF89a'} and len(payload) >= 14 and payload[-1] == 0x3b:
        return struct.unpack('<HH', payload[6:10])
    if media_type == 'image/jpeg' and payload.startswith(b'\xff\xd8') and payload.endswith(b'\xff\xd9'):
        offset = 2
        while offset + 9 < len(payload):
            if payload[offset] != 0xff:
                offset += 1
                continue
            marker = payload[offset + 1]
            offset += 2
            if marker in {0xd8, 0xd9}:
                continue
            length = int.from_bytes(payload[offset:offset + 2], 'big')
            if length < 2 or offset + length > len(payload):
                break
            if marker in {0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf}:
                return int.from_bytes(payload[offset + 5:offset + 7], 'big'), int.from_bytes(payload[offset + 3:offset + 5], 'big')
            offset += length
    if media_type == 'image/webp' and payload.startswith(b'RIFF') and payload[8:12] == b'WEBP' and len(payload) >= 20 and int.from_bytes(payload[4:8], 'little') + 8 <= len(payload):
        chunk, data = payload[12:16], payload[20:]
        if chunk == b'VP8X' and len(data) >= 10:
            return 1 + int.from_bytes(data[4:7], 'little'), 1 + int.from_bytes(data[7:10], 'little')
        if chunk == b'VP8L' and len(data) >= 5 and data[0] == 0x2f:
            bits = int.from_bytes(data[1:5], 'little')
            return (bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1
        if chunk == b'VP8 ' and len(data) >= 10 and data[3:6] == b'\x9d\x01\x2a':
            return int.from_bytes(data[6:8], 'little') & 0x3fff, int.from_bytes(data[8:10], 'little') & 0x3fff
    _reject('图片内容与声明的类型不匹配')


def validate_attachments(value, model_profile):
    if value is None:
        return []
    if isinstance(value, str):
        # Frappe RPC may encode nested parameters as JSON strings.
        if len(value) > 56 * 1024 * 1024:
            _reject('附件请求过大')
        try:
            value = json.loads(value)
        except ValueError:
            _reject('附件列表无效')
    if not isinstance(value, list) or len(value) > 4:
        _reject('每次最多上传 4 个附件')
    result, totals = [], dict(text=0, document=0, image=0)
    for item in value:
        if not isinstance(item, dict) or set(item) != {'file_name', 'media_type', 'content_base64'}:
            _reject('附件字段无效')
        name = _filename(item['file_name'])
        media = item['media_type'].strip().lower() if isinstance(item['media_type'], str) else ''
        if media not in TEXT_TYPES | IMAGE_TYPES | DOCUMENT_TYPES.keys():
            _reject('不支持此附件类型')
        category = 'image' if media in IMAGE_TYPES else 'document' if media in DOCUMENT_TYPES else 'text'
        if category == 'image' and model_profile != 'deepseek-v4-flash-executor-v1':
            _reject('当前模型不支持图片；请选择 DeepSeek Flash')
        payload = _decode(item['content_base64'], ATTACHMENT_LIMITS[category + '_file_bytes'])
        totals[category] += len(payload)
        if totals[category] > ATTACHMENT_LIMITS[category + '_total_bytes']:
            _reject('附件总大小超过此类型的上限')
        if category == 'text':
            try:
                text = payload.decode('utf-8')
            except UnicodeDecodeError:
                _reject('文本附件必须使用 UTF-8 编码')
            if not text.strip():
                _reject('文本附件不能为空')
        elif category == 'document':
            if not name.lower().endswith(DOCUMENT_TYPES[media]):
                _reject('文档扩展名与类型不匹配')
            # ponytail: native Cloud performs bounded document extraction and its
            # extracted-text total limit; the Host validates transport and type.
            if not payload.startswith(b'%PDF-' if media == 'application/pdf' else b'PK\x03\x04'):
                _reject('文档内容与声明的类型不匹配')
        else:
            width, height = _image_dimensions(payload, media)
            if not (0 < width <= 8192 and 0 < height <= 8192) or width * height > 36000000:
                _reject('图片尺寸超过上限')
        result.append(dict(file_name=name, media_type=media, content_base64=base64.b64encode(payload).decode('ascii')))
    return result


def attachment_digest(attachments):
    """Bind names, MIME, ordered bytes without retaining another payload copy."""
    coordinates = [dict(file_name=a['file_name'], media_type=a['media_type'],
        sha256=hashlib.sha256(base64.b64decode(a['content_base64'], validate=True)).hexdigest()) for a in attachments]
    return hashlib.sha256(json.dumps(coordinates, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}', value) or value in {'.', '..'}:
        _reject('资源标识无效')
    return quote(value, safe='')


def _json(doc, suffix, *, limit=2 * 1024 * 1024, params=None):
    response = cloud.request(doc, 'GET', '/tasks/' + _id(doc.task_id) + suffix,
        params=params, stream=True, raw_response=True)
    try:
        if response.status_code != 200:
            _reject('Zebra Cloud 资源暂不可用（%s）' % response.status_code)
        payload = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            payload.extend(chunk)
            if len(payload) > limit:
                _reject('Zebra Cloud 资源响应超过上限')
        try:
            value = json.loads(payload)
        except (ValueError, UnicodeError):
            _reject('Zebra Cloud 资源响应无效')
        if not isinstance(value, dict):
            _reject('Zebra Cloud 资源响应无效')
        return value
    finally:
        response.close()


def _envelope(doc):
    return dict(conversation=doc.name, history_scope='active_segment')


def _number(value):
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None


def usage(conversation):
    doc = cloud.owned(conversation)
    value = _json(doc, '/usage') if doc.task_id else {}
    model = value.get('model_usage') or {}
    model = model if isinstance(model, dict) else {}
    allowed = ('model_call_count', 'cache_hit_tokens', 'cache_miss_tokens', 'input_tokens', 'input_token_limit')
    projection = {k: _number(model[k]) for k in allowed if _number(model.get(k)) is not None}
    for key in ('model', 'reasoning_effort'):
        if isinstance(model.get(key), str):
            projection[key] = model[key][:200]
    return dict(conversation=doc.name, history_scope='task', model_usage=projection or None,
        **{k: _number(value.get(k)) for k in ('through_sequence', 'attachment_count', 'attachment_bytes')})


def attachments(conversation, cursor=None):
    """Task-wide metadata page; attachment bodies remain inside native storage."""
    doc = cloud.owned(conversation)
    if cursor is not None and (not isinstance(cursor, str) or not 1 <= len(cursor) <= 512):
        _reject('附件分页标识无效')
    params = dict(limit=64, max_bytes=262144)
    if cursor:
        params['cursor'] = cursor
    value = _json(doc, '/attachments', params=params) if doc.task_id else {}
    rows = value.get('attachments', [])
    if not isinstance(rows, list) or len(rows) > 64:
        _reject('附件列表响应无效')
    result = []
    for row in rows:
        if not isinstance(row, dict):
            _reject('附件列表响应无效')
        entry = {}
        for key in ('attachment_id', 'message_event_id', 'file_name', 'media_type', 'original_media_type', 'extraction_status'):
            if isinstance(row.get(key), str):
                entry[key] = row[key][:255]
        for key in ('size_bytes', 'original_size_bytes', 'image_width', 'image_height', 'page_count', 'paragraph_count', 'worksheet_count', 'cell_count', 'slide_count'):
            if _number(row.get(key)) is not None:
                entry[key] = row[key]
        result.append(entry)
    next_cursor = value.get('next_cursor')
    if next_cursor is not None and (not isinstance(next_cursor, str) or len(next_cursor) > 512):
        _reject('附件分页响应无效')
    return dict(conversation=doc.name, history_scope='task', attachments=result,
        has_more=value.get('has_more') is True, next_cursor=next_cursor,
        **{k: _number(value.get(k)) for k in ('through_sequence', 'attachment_count', 'attachment_bytes')})


def _artifact(value):
    if not isinstance(value, dict):
        _reject('成果资源响应无效')
    artifact_id = value.get('artifact_id')
    _id(artifact_id)
    result = dict(artifact_id=artifact_id)
    for key, limit in (('label', 255), ('kind', 100), ('source', 100), ('preview', 100000)):
        if isinstance(value.get(key), str):
            result[key] = value[key][:limit]
    result['sequence'] = _number(value.get('sequence'))
    for group, fields in {'preview_state': ('redacted', 'truncated'), 'access': ('allowed',)}.items():
        nested = value.get(group) or {}
        result[group] = {k: nested[k] for k in fields if isinstance(nested, dict) and type(nested.get(k)) is bool}
    retrieval = value.get('retrieval') or {}
    result['retrieval'] = {'status': str(retrieval.get('status', 'unavailable'))[:100]} if isinstance(retrieval, dict) else {'status': 'unavailable'}
    if result['access'].get('allowed') is not True:
        result.pop('preview', None)
    delivery = value.get('delivery') or {}
    result['delivery'] = {}
    if isinstance(delivery, dict):
        name = delivery.get('file_name')
        # Never send filesystem paths or response-header content supplied upstream.
        if isinstance(name, str) and len(name) <= 255 and name not in {'.', '..'} and not any(c in name for c in '/\\') and not any(ord(c) < 32 or ord(c) == 127 for c in name):
            result['delivery']['file_name'] = name
        media = delivery.get('mime_type')
        if isinstance(media, str) and re.fullmatch(r'[\w.+-]+/[\w.+-]+', media):
            result['delivery']['mime_type'] = media
        result['delivery']['size_bytes'] = _number(delivery.get('size_bytes'))
    return result


def artifacts(conversation):
    doc = cloud.owned(conversation)
    rows = _json(doc, '/artifacts').get('artifacts', []) if doc.task_id else []
    if not isinstance(rows, list):
        _reject('成果资源列表无效')
    return dict(**_envelope(doc), artifacts=[_artifact(row) for row in rows[:200]], has_more=len(rows) > 200)


def artifact_detail(conversation, artifact_id):
    doc = cloud.owned(conversation)
    value = _json(doc, '/artifacts/' + _id(artifact_id))
    artifact = _artifact(value.get('artifact'))
    if artifact['artifact_id'] != artifact_id:
        _reject('成果资源归属不匹配')
    return dict(**_envelope(doc), artifact=artifact)


def artifact_content(conversation, artifact_id):
    doc = cloud.owned(conversation)
    detail = artifact_detail(conversation, artifact_id)['artifact']
    if detail['access'].get('allowed') is not True:
        _reject('当前会话策略不允许读取此成果资源')
    delivery = detail['delivery']
    size = delivery.get('size_bytes')
    if type(size) is not int or not 0 <= size <= MAX_ARTIFACT_BYTES:
        _reject('成果资源大小未知或超过 20 MiB 下载上限')
    value = _json(doc, '/artifacts/' + _id(artifact_id) + '/content', limit=((size + 2) // 3) * 4 + 65536)
    if value.get('artifact_id') != artifact_id or value.get('encoding') != 'base64' or value.get('status') != 'ok':
        _reject('成果资源内容响应无效')
    payload = _decode(value.get('content_base64'), size, allow_empty=True)
    if len(payload) != size or value.get('size_bytes') != size:
        _reject('成果资源大小校验失败')
    return dict(**_envelope(doc), artifact_id=artifact_id, status='ok', encoding='base64',
        content_base64=base64.b64encode(payload).decode('ascii'), size_bytes=size,
        file_name=delivery.get('file_name') or artifact_id, media_type=delivery.get('mime_type') or 'application/octet-stream')


def artifact_download(conversation, artifact_id):
    return artifact_content(conversation, artifact_id)


def preview_mime(name, media):
    safe = {'txt': 'text/plain', 'md': 'text/markdown', 'csv': 'text/csv', 'json': 'application/json',
        'pdf': 'application/pdf', 'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'webp': 'image/webp', 'gif': 'image/gif',
        'mp4': 'video/mp4', 'webm': 'video/webm', 'ogg': 'video/ogg'}
    if isinstance(name, str) and name.lower().endswith('.json') and media in {'application/vnd.vegalite+json', 'application/vnd.vegalite.v6+json'}:
        return 'application/json'
    return media if isinstance(name, str) and safe.get(name.rsplit('.', 1)[-1].lower()) == media else None
