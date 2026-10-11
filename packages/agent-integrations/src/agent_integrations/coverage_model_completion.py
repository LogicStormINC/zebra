"""Versioned full MODEL checkpoints, including provider-private message fields."""

import json
import math
from collections.abc import Mapping
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from enum import Enum
from types import MappingProxyType, UnionType
from typing import Any, get_args, get_origin, get_type_hints
from uuid import UUID, SafeUUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import (
    ModelCallMetadata,
    ModelCompletion,
    ModelTokenBreakdown,
    ModelUsage,
)
from agent_core.domain.tools import ToolCall
from pydantic import BaseModel

MAX_MODEL_COMPLETION_BYTES = 32 * 1024 * 1024
_RECORDS: tuple[type[Any], ...] = (
    ModelCompletion,
    ModelCallMetadata,
    ModelUsage,
    ModelTokenBreakdown,
    SessionMessage,
    ToolCall,
)
_FIELDS = {
    cls: {
        name: hint
        for name, hint in get_type_hints(cls).items()
        if name
        in (
            cls.model_fields
            if issubclass(cls, BaseModel)
            else {field.name for field in fields(cls)}
        )
    }
    for cls in _RECORDS
}


def encode_model_completion(completion: ModelCompletion) -> bytes:
    """Validate raw runtime values, then encode all fields.

    Unsupported custom objects and normalization-changing mutations are rejected.
    Integrity and authority belong to the enclosing durable envelope/Artifact.
    """
    try:
        validated = _read(completion, ModelCompletion, wire=False)
        body = _json_value(validated)
        encoded = _canonical(
            {
                "schema_version": 1,
                "completion": body,
            }
        )
        if len(encoded) > MAX_MODEL_COMPLETION_BYTES:
            raise ValueError("model completion checkpoint exceeds byte limit")
        return encoded
    except (TypeError, AttributeError, RecursionError, OverflowError) as exc:
        raise ValueError("invalid model completion checkpoint") from exc


def decode_model_completion(checkpoint: bytes) -> ModelCompletion:
    """Restore the complete typed response without a provider call.

    Missing optional fields use core defaults; re-encoding always includes defaults.
    Byte bounds apply before parsing, and duplicate keys are invalid at every depth.
    """
    if type(checkpoint) is not bytes or not 0 < len(checkpoint) <= MAX_MODEL_COMPLETION_BYTES:
        raise ValueError("model completion checkpoint must be bounded nonempty bytes")
    try:
        envelope = json.loads(
            checkpoint.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
        )
        if type(envelope) is not dict or set(envelope) != {
            "schema_version",
            "completion",
        }:
            raise ValueError("invalid model completion checkpoint envelope")
        if type(envelope["schema_version"]) is not int or envelope["schema_version"] != 1:
            raise ValueError("unsupported model completion checkpoint schema")
        body = envelope["completion"]
        result: ModelCompletion = _read(body, ModelCompletion, wire=True)
        return result
    except (TypeError, AttributeError, RecursionError, OverflowError, UnicodeError) as exc:
        raise ValueError("invalid model completion checkpoint") from exc


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        _utf8(key)
        if key in result:
            raise ValueError("duplicate checkpoint JSON key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> Any:
    raise ValueError("nonfinite checkpoint JSON number")


def _utf8(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("checkpoint string must be UTF-8 representable") from None
    return value


def _read(value: Any, hint: Any, *, wire: bool) -> Any:
    """Check raw shapes before invoking any core constructor or Pydantic validator."""
    if hasattr(hint, "__supertype__"):
        hint = hint.__supertype__
    origin, args = get_origin(hint), get_args(hint)
    if origin is UnionType:
        for alternative in args:
            try:
                return _read(value, alternative, wire=wire)
            except ValueError:
                pass
        raise ValueError("invalid checkpoint union value")
    if hint in _RECORDS:
        return _record(value, hint, wire=wire)
    if hint is Any or hint is object:
        return _json_tree(value)
    if origin in (dict, Mapping):
        allowed = (dict, MappingProxyType) if origin is Mapping and not wire else (dict,)
        if type(value) not in allowed:
            raise ValueError("checkpoint mapping must have a supported raw shape")
        return {
            _read(key, args[0], wire=wire): _read(item, args[1], wire=wire)
            for key, item in value.items()
        }
    if origin is tuple:
        if type(value) is not (list if wire else tuple):
            raise ValueError("invalid checkpoint tuple shape")
        return tuple(_read(item, args[0], wire=wire) for item in value)
    if hint is datetime or hint is UUID or (isinstance(hint, type) and issubclass(hint, Enum)):
        if hint is datetime:
            return _timestamp(value, wire=wire)
        scalar_type: Any = hint
        if wire:
            if type(value) is not str:
                raise ValueError("checkpoint typed scalar must be a string")
            _utf8(value)
            result: Any = scalar_type(value)
        else:
            if type(value) is not hint:
                raise ValueError("invalid checkpoint typed scalar")
            result = value
        if hint is UUID:
            if type(result.int) is not int or type(result.is_safe) is not SafeUUID:
                raise ValueError("invalid checkpoint UUID internal state")
            if UUID(int=result.int) != result or UUID(str(result)) != result:
                raise ValueError("noncanonical checkpoint UUID")
        elif (
            type(result.value) is not str
            or str(result) != result.value
            or scalar_type.__members__.get(result.name) is not result
            or scalar_type(result.value) is not result
        ):
            raise ValueError("invalid checkpoint enum internal state")
        return result
    if hint is float and type(value) in (int, float) and math.isfinite(value):
        return value
    if type(value) is not hint:
        raise ValueError("invalid checkpoint scalar type")
    if hint is str:
        return _utf8(value)
    if hint is float and not math.isfinite(value):
        raise ValueError("nonfinite checkpoint number")
    return value


def _timestamp(value: Any, *, wire: bool) -> datetime:
    if wire:
        if type(value) is str:
            restored = datetime.fromisoformat(_utf8(value))
            if restored.isoformat() != value:
                raise ValueError("checkpoint timestamp requires lossy normalization")
            value = restored
        elif type(value) is dict and set(value) == {"iso", "offset_us", "fold"}:
            if (
                type(value["iso"]) is not str
                or type(value["offset_us"]) is not int
                or not -86_400_000_000 < value["offset_us"] < 86_400_000_000
                or type(value["fold"]) is not int
                or value["fold"] not in (0, 1)
            ):
                raise ValueError("invalid checkpoint fixed-offset timestamp")
            restored = datetime.fromisoformat(_utf8(value["iso"])).replace(
                tzinfo=timezone(timedelta(microseconds=value["offset_us"])),
                fold=value["fold"],
            )
            if restored.isoformat() != value["iso"]:
                raise ValueError("checkpoint fixed offset and ISO timestamp disagree")
            value = restored
        elif type(value) is dict and set(value) == {"iso", "zone", "fold"}:
            if (
                type(value["iso"]) is not str
                or type(value["zone"]) is not str
                or type(value["fold"]) is not int
                or value["fold"] not in (0, 1)
            ):
                raise ValueError("invalid checkpoint zoned timestamp")
            try:
                restored = datetime.fromisoformat(_utf8(value["iso"])).replace(
                    tzinfo=ZoneInfo(_utf8(value["zone"])),
                    fold=value["fold"],
                )
            except ZoneInfoNotFoundError as exc:
                raise ValueError("unknown checkpoint timezone") from exc
            if restored.isoformat() != value["iso"]:
                raise ValueError("checkpoint timezone and offset disagree")
            value = restored
        else:
            raise ValueError("invalid checkpoint timestamp shape")
    if (
        type(value) is not datetime
        or type(value.tzinfo) not in (timezone, ZoneInfo)
        or value.utcoffset() is None
    ):
        raise ValueError("checkpoint timestamp requires a supported aware timezone")
    # ponytail: fixed stdlib timezones and canonical cached zones only; other timezone
    # identities need an explicit equality-preserving wire contract, not just a zone key.
    if type(value.tzinfo) is ZoneInfo and (
        type(value.tzinfo.key) is not str or value.tzinfo is not ZoneInfo(value.tzinfo.key)
    ):
        raise ValueError("checkpoint timezone requires a canonical cached zone")
    result: datetime = value
    return result


def _record(value: Any, cls: Any, *, wire: bool) -> Any:
    names = _FIELDS[cls]
    if wire:
        if type(value) is not dict:
            raise ValueError("checkpoint record must be an object")
        raw = value
    else:
        if type(value) is not cls:
            raise ValueError("unsupported checkpoint runtime record")
        raw = vars(value)
        if isinstance(value, BaseModel) and (
            value.__pydantic_extra__ is not None or value.__pydantic_private__ is not None
        ):
            raise ValueError("checkpoint model contains extra state")
        if set(raw) != set(names):
            raise ValueError("checkpoint runtime record has missing or extra fields")
    if set(raw) - set(names):
        raise ValueError("unknown checkpoint record fields")
    typed = {name: _read(item, names[name], wire=wire) for name, item in raw.items()}
    result = cls.model_validate(typed, strict=True) if issubclass(cls, BaseModel) else cls(**typed)
    # Reject illicit model_copy values that field validators would silently normalize.
    if any(getattr(result, name) != item for name, item in typed.items()):
        raise ValueError("checkpoint record requires lossy normalization")
    return result


def _json_value(value: Any) -> Any:
    if type(value) in _RECORDS:
        return {name: _json_value(getattr(value, name)) for name in _FIELDS[type(value)]}
    if type(value) is UUID:
        return str(value)
    if type(value) is datetime:
        if type(value.tzinfo) is ZoneInfo:
            return {"iso": value.isoformat(), "zone": value.tzinfo.key, "fold": value.fold}
        offset = value.utcoffset()
        assert offset is not None  # _timestamp already validated awareness.
        return {
            "iso": value.isoformat(),
            "offset_us": offset // timedelta(microseconds=1),
            "fold": value.fold,
        }
    if isinstance(value, Enum):
        return value.value
    if type(value) is tuple:
        # Only typed tuple fields reach here; arbitrary metadata uses _json_tree.
        return [_json_value(item) for item in value]
    return _json_tree(value)


def _json_tree(value: Any) -> Any:
    if type(value) is str:
        return _utf8(value)
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) is list:
        return [_json_tree(item) for item in value]
    if type(value) is dict and all(type(key) is str for key in value):
        return {_utf8(key): _json_tree(item) for key, item in value.items()}
    raise ValueError("unsupported checkpoint JSON value")
