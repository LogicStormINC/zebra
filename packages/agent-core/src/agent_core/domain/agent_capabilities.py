"""Stable Zebra capability vocabulary kept separate from Host Grant scopes.

ADR-017 decision 3: a ``Capability`` is a Zebra-side stable semantic name
(``evidence.read``); a ``GrantScope`` is Host-owned authorization wording
(``trench:event:read``). Hosts map their scopes onto Zebra capabilities via
manifest ``required_grant_scopes``; Zebra never imports Host vocabulary into
its own ceilings.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import reduce
from typing import NewType

CAPABILITY_PATTERN = re.compile(r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+$")
MAX_CAPABILITY_LENGTH = 128
MAX_CAPABILITY_COUNT = 256

Capability = NewType("Capability", str)
GrantScope = NewType("GrantScope", str)


def capability(value: str) -> Capability:
    """Validate and normalise one stable Zebra capability name."""

    text = value.strip()
    if not text or len(text) > MAX_CAPABILITY_LENGTH:
        raise ValueError("capability must be bounded and non-blank")
    if CAPABILITY_PATTERN.fullmatch(text) is None:
        raise ValueError(f"capability is not a dotted stable name: {value!r}")
    return Capability(text)


def grant_scope(value: str) -> GrantScope:
    """Validate one Host-owned scope token without constraining its wording."""

    text = value.strip()
    if not text or len(text) > MAX_CAPABILITY_LENGTH:
        raise ValueError("grant scope must be bounded and non-blank")
    if any(character.isspace() for character in text):
        raise ValueError("grant scope must not contain whitespace")
    return GrantScope(text)


def capability_set(values: Iterable[str]) -> frozenset[Capability]:
    """Validate a bounded, duplicate-free capability set."""

    items = [capability(value) for value in values]
    if len(items) > MAX_CAPABILITY_COUNT:
        raise ValueError("capability set exceeds its bound")
    if len(set(items)) != len(items):
        raise ValueError("capability set contains duplicates")
    return frozenset(items)


def grant_scope_set(values: Iterable[str]) -> frozenset[GrantScope]:
    """Validate a bounded, duplicate-free grant scope set."""

    items = [grant_scope(value) for value in values]
    if len(items) > MAX_CAPABILITY_COUNT:
        raise ValueError("grant scope set exceeds its bound")
    if len(set(items)) != len(items):
        raise ValueError("grant scope set contains duplicates")
    return frozenset(items)


def intersect_capabilities(*sets: frozenset[Capability]) -> frozenset[Capability]:
    """Intersect capability sets; the empty intersection authorises nothing."""

    if not sets:
        raise ValueError("at least one capability set is required")
    return reduce(lambda left, right: left & right, sets)
