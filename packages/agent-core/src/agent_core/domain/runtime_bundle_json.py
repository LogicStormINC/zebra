"""The bounded integer/ASCII canonical JSON profile used by Bundle v1."""

import hashlib
import json
from typing import Any

MAX_BUNDLE_BYTES = 262_144
MAX_BUNDLE_DEPTH = 24
MAX_BUNDLE_NODES = 8192


def validate_json_tree(value: object) -> None:
    pending = [(value, 1)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > MAX_BUNDLE_DEPTH or nodes > MAX_BUNDLE_NODES:
            raise ValueError("JSON limit exceeded")
        if isinstance(item, str):
            if any(0xD800 <= ord(char) <= 0xDFFF for char in item):
                raise ValueError("invalid Unicode")
        elif item is None or type(item) is bool:
            pass
        elif type(item) is int:
            if not -(2**63) <= item <= 2**63 - 1:
                raise ValueError("integer limit exceeded")
        elif type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise ValueError("JSON key required")
                pending.extend(((key, depth + 1), (child, depth + 1)))
        elif type(item) is list or type(item) is tuple:
            pending.extend((child, depth + 1) for child in item)
        else:
            raise ValueError("unsupported JSON value")


def canonical_json_bytes(value: object) -> bytes:
    validate_json_tree(value)
    result = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode(
        "ascii"
    )
    if len(result) > MAX_BUNDLE_BYTES:
        raise ValueError("JSON size limit exceeded")
    return result


def json_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _no_float(value: str) -> None:
    raise ValueError("integer JSON profile required")


def load_bundle_json(raw: bytes, *, max_bytes: int = MAX_BUNDLE_BYTES) -> Any:
    if type(raw) is not bytes or len(raw) > max_bytes or raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("invalid JSON bytes")
    decoded = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_object,
        parse_float=_no_float,
        parse_constant=_no_float,
    )
    validate_json_tree(decoded)
    return decoded
