"""Production literal checks and strictly validated configured model extraction."""

from collections.abc import Callable
from itertools import chain, islice

from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_core.domain.coverage_execution import (
    CoverageObservation,
    CoverageQuote,
    PublishedCoverageCheck,
)
from agent_core.domain.coverage_task_admission import coverage_admission_input
from agent_core.domain.coverage_validation import CoverageUnitKey

ModelCheck = Callable[[PublishedCoverageCheck, CoverageUnitKey, dict[str, str]], object]


def merge_observations(
    key: CoverageUnitKey, part_ids: tuple[str, ...], prior: tuple[CoverageObservation, ...]
) -> CoverageObservation:
    prior = tuple(
        CoverageObservation.model_validate(coverage_admission_input(item), strict=True)
        for item in prior
    )
    if (
        key.kind != "record_merge"
        or not prior
        or tuple(item.key.part_id for item in prior) != part_ids
        or len(set(part_ids)) != len(part_ids)
        or any(
            item.key.kind != "part"
            or (
                item.key.record_id,
                item.key.content_digest,
                item.key.check_id,
                item.key.check_version,
                item.key.definition_digest,
            )
            != (
                key.record_id,
                key.content_digest,
                key.check_id,
                key.check_version,
                key.definition_digest,
            )
            for item in prior
        )
    ):
        raise ValueError("record merge requires accepted matching canonical parts in order")
    # ponytail: display at most 100 quotes; every part remains linked by digest.
    return CoverageObservation(
        key=key,
        outcome="finding" if any(item.outcome == "finding" for item in prior) else "clear",
        summary="Merged all canonical parts",
        quotes=tuple(islice(chain.from_iterable(item.quotes for item in prior), 100)),
        part_result_digests=tuple(item.digest for item in prior),
    )


class PublishedCoverageRunner:
    def __init__(
        self, definitions: tuple[PublishedCoverageCheck, ...], *, model: ModelCheck | None = None
    ) -> None:
        self.definitions = {definition.id: definition for definition in definitions}
        if len(self.definitions) != len(definitions):
            raise ValueError("duplicate published check IDs")
        self.model = model

    def run(
        self,
        key: CoverageUnitKey,
        bodies: dict[str, str],
        *,
        prior: tuple[CoverageObservation, ...],
    ) -> CoverageObservation:
        definition = self.definitions.get(key.check_id)
        if definition is None or (
            definition.contract_check.version != key.check_version
            or definition.contract_check.definition_digest != key.definition_digest
        ):
            raise CoverageRefusedError(CoverageRefusalReason.UNSUPPORTED)
        if key.kind == "record_merge":
            result = merge_observations(key, tuple(bodies), prior)
        elif definition.implementation == "literal_contains/1":
            found: list[CoverageQuote] = []
            for part_id, body in bodies.items():
                for term in definition.terms:
                    offset = body.find(term)
                    if offset >= 0:
                        found.append(
                            CoverageQuote(
                                part_id=part_id, start=offset, end=offset + len(term), text=term
                            )
                        )
            result = CoverageObservation(
                key=key,
                outcome="finding" if found else "clear",
                summary="Literal term check; not a semantic risk judgment",
                quotes=tuple(found),
            )
        else:
            if self.model is None:
                raise CoverageRefusedError(CoverageRefusalReason.UNSUPPORTED)
            if sum(len(body) for body in bodies.values()) > definition.max_part_characters:
                # No truncation: the unprocessed unit stays missing for a supported runner.
                raise CoverageRefusedError(CoverageRefusalReason.UNSUPPORTED)
            result = CoverageObservation.model_validate(
                coverage_admission_input(self.model(definition, key, bodies)), strict=True
            )
        if result.key != key:
            raise ValueError("model result binds another coverage unit")
        result.validate_source(bodies)
        return result
