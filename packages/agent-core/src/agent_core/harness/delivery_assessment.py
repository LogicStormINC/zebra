"""Delivery metadata and conservative, source-bound version-scope qualification."""

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import TypedDict
from urllib.parse import urlsplit

from agent_core.domain.modeling import ModelCompletion

_VERSION = r"\d{1,4}(?:\.\d{1,4}){0,3}(?:\.[xX*])?"
_REQUEST = re.compile(
    rf"(?<![A-Za-z0-9_/.-])([A-Za-z][A-Za-z_+.-]{{1,63}}?)[ \t]+"
    rf"(?:v(?=\d))?({_VERSION})(?![A-Za-z0-9_.])"
)
_URL = re.compile(r"https?://[^\s<>`\"\])]+")


class CheckedVersionScope(TypedDict):
    subject: str
    versions: list[str]
    source_refs: list[str]
    basis: str


class UnresolvedVersionScope(TypedDict):
    subject: str
    requested_version: str
    reason: str
    observed_versions: list[str]


class VersionScopeReport(TypedDict):
    requested_scope: list[dict[str, str]]
    checked_scope: list[CheckedVersionScope]
    unresolved_points: list[UnresolvedVersionScope]
    status: str
    semantic_coverage_certified: bool


@dataclass(frozen=True)
class RequestedVersionScope:
    subject: str
    version: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z][A-Za-z_+.-]{1,63}", self.subject):
            raise ValueError("version scope subject must be a bounded product token")
        if not re.fullmatch(_VERSION, self.version):
            raise ValueError("version scope version must be a bounded version literal")


def requested_version_scopes(goal: str) -> tuple[RequestedVersionScope, ...]:
    # ponytail: explicit Latin product/version literals only, not semantic scope inference.
    # Ambiguous names/ranges need an explicit Host contract; never expand a major into minors.
    scopes: dict[tuple[str, str], RequestedVersionScope] = {}
    for match in _REQUEST.finditer(goal):
        subject, version = match.groups()
        scopes.setdefault((subject.casefold(), version.casefold()),
                          RequestedVersionScope(subject, version))
        if len(scopes) == 12:
            break
    return tuple(scopes.values())


def assess_version_scopes(
    requested: tuple[RequestedVersionScope, ...],
    answer: str,
    receipts: Iterable[Mapping[str, object]],
) -> VersionScopeReport:
    citations = {m.group().rstrip(".,;:!?，。；：！？") for m in _URL.finditer(answer)}
    found: dict[str, dict[str, set[str]]] = {s.subject.casefold(): {} for s in requested}
    for receipt in receipts:
        if receipt.get("tool_name") != "web.fetch" or receipt.get("status") != "executed":
            continue
        metadata = receipt.get("metadata")
        text = receipt.get("output")
        if not isinstance(metadata, Mapping) or not isinstance(text, str):
            continue
        url = metadata.get("url")
        if not isinstance(url, str) or len(url) > 2048 or url not in citations:
            continue
        try:
            parts = urlsplit(url).path.split("/")
        except ValueError:
            continue
        for part in parts:
            match = re.fullmatch(r"(?:v|release-)?(\d{1,4}(?:[.-]\d{1,4}){0,3})"
                                 r"(?:\.html|\.md)?", part)
            if match is None:
                continue
            version = match[1].replace("-", ".")
            for scope in requested:
                # URL alone is not a version attestation: require matching product/version
                # in the returned header as well. Unknown layouts remain unresolved.
                pattern = (rf"(?<![A-Za-z0-9_]){re.escape(scope.subject)}\s+v?"
                           rf"{re.escape(version)}(?![A-Za-z0-9_.])")
                if re.search(pattern, text[:4096], re.IGNORECASE):
                    sources = found[scope.subject.casefold()]
                    if version in sources or len(sources) < 12:
                        refs = sources.setdefault(version, set())
                        if len(refs) < 32:
                            refs.add(url)
    checked: list[CheckedVersionScope] = []
    unresolved: list[UnresolvedVersionScope] = []
    for scope in requested:
        sources = found[scope.subject.casefold()]
        checked.append({"subject": scope.subject, "versions": sorted(sources),
                        "source_refs": sorted({u for refs in sources.values() for u in refs})[:32],
                        "basis": "cited_fetched_source_version_only"})
        if scope.version not in sources:
            unresolved.append({"subject": scope.subject, "requested_version": scope.version,
                               "reason": "requested_version_scope_not_established",
                               "observed_versions": sorted(sources)})
    return {"requested_scope": [{"subject": s.subject, "version": s.version} for s in requested],
            "checked_scope": checked, "unresolved_points": unresolved,
            "status": "partial" if unresolved else "matched",
            "semantic_coverage_certified": False}


def qualify_version_scope(
    completion: ModelCompletion,
    delivery: dict[str, object],
    contract: object | None,
    receipts: Iterable[Mapping[str, object]],
) -> tuple[ModelCompletion, dict[str, object]]:
    scopes = getattr(contract, "version_scopes", ())
    if not scopes:
        return completion, delivery
    report = assess_version_scopes(scopes, completion.assistant_message.content, receipts)
    delivery = {**delivery, "version_scope": report}
    if report["status"] == "matched":
        return completion, delivery
    unmet = delivery.get("unmet", [])
    satisfied = delivery.get("satisfied", [])
    delivery.update(
        status="partial",
        unmet=[*(unmet if isinstance(unmet, list) else []), "version_scope_unresolved"],
        satisfied=[s for s in (satisfied if isinstance(satisfied, list) else [])
                   if s != "task_acceptance_contract"],
    )
    answer = completion.assistant_message.content
    goal = str(getattr(contract, "goal", ""))
    chinese = any("\u4e00" <= ch <= "\u9fff" for ch in goal)
    ranges = "; ".join(f"{item['subject']}: {', '.join(item['versions']) or '?'}"
                       for item in report["checked_scope"])
    notice = (
        f"版本范围说明：已核对的引用来源版本为 {ranges}。请求范围仍有未决点，"
        "以上属于部分覆盖，不能据此认定整个请求版本范围已完整核对。"
        if chinese else
        f"Version scope: cited source versions checked: {ranges}. Requested scope remains "
        "unresolved; this is partial coverage, not verification of the entire requested range."
    )
    try:
        json.loads(answer)
        structured = True
    except (ValueError, RecursionError):
        structured = answer.lstrip().startswith("```")
    qualified = f"{answer.rstrip()}\n\n{notice}"
    maximum = getattr(contract, "max_characters", None)
    if not structured and (maximum is None or len(qualified) <= maximum):
        completion = replace(completion, assistant_message=completion.assistant_message.model_copy(
            update={"content": qualified}
        ))
    return completion, delivery


def _delivery_assessment(
    status: str,
    *,
    satisfied: tuple[str, ...] = (),
    unmet: tuple[str, ...] = (),
    evidence_refs: tuple[str, ...] = (),
    media_refs: tuple[str, ...] = (),
    artifact_refs: tuple[str, ...] = (),
    contract: object | None = None,
) -> dict[str, object]:
    required_outcomes = tuple(getattr(contract, "required_outcomes", ()))
    result: dict[str, object] = {
        "status": status,
        "satisfied": list(satisfied),
        "unmet": list(unmet),
        "evidence_refs": list(evidence_refs),
        "media_refs": list(media_refs),
        "artifact_refs": list(artifact_refs),
    }
    if contract is not None:
        result["task_type"] = str(getattr(contract, "task_type", ""))
        result["goal"] = str(getattr(contract, "goal", ""))
        result["required_outcomes"] = list(required_outcomes)
    return result
