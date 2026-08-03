from __future__ import annotations


def resolve_context_namespace(
    administrative_context_namespace: str | None,
    context_administrative_namespace: str | None,
) -> str | None:
    if (
        administrative_context_namespace is not None
        and context_administrative_namespace is not None
        and administrative_context_namespace != context_administrative_namespace
    ):
        raise ValueError("Context administrative namespace aliases must match")
    return administrative_context_namespace or context_administrative_namespace
