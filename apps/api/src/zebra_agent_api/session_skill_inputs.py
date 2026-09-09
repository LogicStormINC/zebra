"""Canonical Skill ceiling input shared by HTTP authorization and admission."""

from agent_core.domain.skills import normalize_skill_components

from zebra_agent_api.responses import ApiResponse, bad_request


def parse_skill_components(payload: dict[str, object]) -> tuple[str, ...] | ApiResponse:
    raw = payload.get("skill_components", [])
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        return bad_request("skill_components must be a list of strings")
    try:
        return normalize_skill_components(raw)
    except ValueError as exc:
        return bad_request(str(exc))
