"""Deterministic boundary checks; these do not measure model semantic accuracy."""

import pytest
from agent_core.application.coverage_checks import PublishedCoverageRunner
from agent_core.application.coverage_semantic import (
    SemanticCoverageResult,
    semantic_check,
    validate_semantic_result,
)
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_core.domain.coverage_validation import CoverageUnitKey
from pydantic import ValidationError

CATEGORIES = (
    "explicit_operational_or_harm_claim",
    "within_part_contradiction",
    "consequential_unsupported_assertion_or_missing_context",
)


def unit(definition):
    check = definition.contract_check
    return CoverageUnitKey(
        record_id="record-1",
        content_digest="a" * 64,
        check_id=check.id,
        check_version=check.version,
        definition_digest=check.definition_digest,
        kind="part",
        part_id="part-1",
        part_digest="b" * 64,
    )


def response(key, body, *, outcome="finding", categories=CATEGORIES[:1]):
    return {
        "key": key.model_dump(mode="json"),
        "outcome": outcome,
        "categories": list(categories),
        "quotes": [{"part_id": "part-1", "start": 0, "end": len(body), "text": body}]
        if outcome == "finding"
        else [],
    }


def run_review(payload, *, body="source"):
    definition = semantic_check(model_profile="review-profile")

    runner = PublishedCoverageRunner(
        (definition,),
        model=lambda definition, key, bodies: validate_semantic_result(
            definition, key, bodies, payload
        ),
    )
    return runner.run(unit(definition), {"part-1": body}, prior=())


@pytest.mark.parametrize(
    "category,body",
    [
        (CATEGORIES[0], "The plant stopped after a toxic leak."),
        (CATEGORIES[1], "Output rose. Output did not rise."),
        (CATEGORIES[2], "Revenue will double; no basis is provided."),
    ],
)
def test_findings_preserve_key_and_exact_source(category, body):
    key = unit(semantic_check(model_profile="review-profile"))
    result = run_review(response(key, body, categories=(category,)), body=body)
    assert result.key == key and result.outcome == "finding"
    assert result.summary == f"Bounded semantic source annotation: {category}"
    assert result.quotes[0].text == body


def test_clear_is_an_explicit_valid_negative():
    key = unit(semantic_check(model_profile="review-profile"))
    result = run_review(response(key, "Routine meeting.", outcome="clear", categories=()))
    assert result.outcome == "clear" and not result.quotes
    assert result.summary == "Bounded semantic source annotation: clear"


def test_unresolved_never_becomes_a_negative():
    key = unit(semantic_check(model_profile="review-profile"))
    with pytest.raises(CoverageRefusedError) as refused:
        run_review(response(key, "source", outcome="unresolved", categories=()))
    assert refused.value.reason == CoverageRefusalReason.UNRESOLVED_REVIEW


@pytest.mark.parametrize(
    "failure",
    (
        "missing_categories missing_quotes empty_categories empty_quotes unknown_category "
        "duplicate_category extra_field confidence free_summary extra_key_field "
        "hallucinated_quote wrong_offset wrong_part extra_quote_field boolean_offset "
        "clear_categories clear_quotes unknown_outcome null string"
    ).split(),
)
def test_invalid_response_is_refused(failure):
    key = unit(semantic_check(model_profile="review-profile"))
    payload = response(key, "source")
    if failure == "missing_categories":
        del payload["categories"]
    elif failure == "missing_quotes":
        del payload["quotes"]
    elif failure == "empty_categories":
        payload["categories"] = []
    elif failure == "empty_quotes":
        payload["quotes"] = []
    elif failure == "unknown_category":
        payload["categories"] = ["investment_advice"]
    elif failure == "duplicate_category":
        payload["categories"] *= 2
    elif failure in {"extra_field", "confidence", "free_summary"}:
        payload[
            {"extra_field": "extra", "confidence": "confidence", "free_summary": "summary"}[failure]
        ] = "untrusted"
    elif failure == "extra_key_field":
        payload["key"]["extra"] = True
    elif failure == "hallucinated_quote":
        payload["quotes"][0]["text"] = "invent"
    elif failure == "wrong_offset":
        payload["quotes"][0]["start"] = 1
    elif failure == "wrong_part":
        payload["quotes"][0]["part_id"] = "other"
    elif failure == "extra_quote_field":
        payload["quotes"][0]["extra"] = True
    elif failure == "boolean_offset":
        payload["quotes"][0]["start"] = False
    elif failure == "clear_categories":
        payload.update(outcome="clear", quotes=[])
    elif failure == "clear_quotes":
        payload.update(outcome="clear", categories=[])
    elif failure == "unknown_outcome":
        payload["outcome"] = "unsupported"
    elif failure == "null":
        payload = None
    elif failure == "string":
        payload = "clear"
    with pytest.raises(CoverageRefusedError) as refused:
        run_review(payload)
    assert refused.value.reason == CoverageRefusalReason.UNSUPPORTED


def test_definition_is_frozen_versioned_and_binds_profile_and_schema():
    definition = semantic_check(model_profile="review-profile")
    assert definition == semantic_check(model_profile="review-profile")
    assert definition.kind == "model" and definition.version == "1"
    assert definition.implementation == "structured_model/1"
    digest = definition.contract_check.definition_digest
    assert digest != semantic_check("other-profile").contract_check.definition_digest
    changed = definition.model_copy(update={"instructions": definition.instructions + " changed"})
    assert digest != changed.contract_check.definition_digest
    assert all(category in definition.instructions for category in CATEGORIES)
    assert all(
        term in definition.instructions
        for term in ("external facts", "investment advice", "confidence", "schema")
    )
    with pytest.raises(ValidationError):
        definition.model_profile = "other-profile"


@pytest.mark.parametrize("profile", [None, "", " ", " padded ", 123])
def test_profile_is_required_and_validated(profile):
    with pytest.raises(ValueError):
        semantic_check(model_profile=profile)


@pytest.mark.parametrize(
    "failure",
    (
        "instructions version implementation missing_model oversize "
        "extra_part missing_part merge key_digest"
    ).split(),
)
def test_unsupported_request_is_refused(failure):
    definition = semantic_check(model_profile="review-profile")
    key = unit(definition)
    bodies = {"part-1": "source"}
    if failure in {"instructions", "version"}:
        definition = definition.model_copy(update={failure: "changed"})
        key = unit(definition)
    elif failure == "implementation":
        definition = definition.model_copy(
            update={
                "id": "literal",
                "kind": "program",
                "implementation": "literal_contains/1",
                "terms": ("source",),
                "model_profile": None,
            }
        )
        key = unit(definition)
    elif failure == "oversize":
        bodies["part-1"] = "x" * (definition.max_part_characters + 1)
    elif failure == "extra_part":
        bodies["part-2"] = ""
    elif failure == "missing_part":
        bodies = {}
    elif failure == "merge":
        key = key.model_copy(update={"kind": "record_merge", "part_id": None, "part_digest": None})
    elif failure == "key_digest":
        key = key.model_copy(update={"definition_digest": "c" * 64})
    with pytest.raises(CoverageRefusedError) as refused:
        if failure == "missing_model":
            PublishedCoverageRunner((definition,)).run(key, bodies, prior=())
        else:
            validate_semantic_result(
                definition, key, bodies, response(key, "source", outcome="clear", categories=())
            )
    assert refused.value.reason == CoverageRefusalReason.UNSUPPORTED


def test_summary_is_stable_for_category_order_and_unicode_offsets():
    definition = semantic_check(model_profile="review-profile")
    key = unit(definition)
    body = "前缀🙂危害"
    payload = response(key, body, categories=CATEGORIES[::-1])
    payload["quotes"] = [{"part_id": "part-1", "start": 3, "end": 5, "text": "危害"}]
    result = run_review(payload, body=body)
    assert result.summary == "Bounded semantic source annotation: " + "; ".join(CATEGORIES)
    payload["categories"].reverse()
    assert run_review(payload, body=body).digest == result.digest


def test_typed_response_and_runner_record_merge():
    definition = semantic_check(model_profile="review-profile")
    key = unit(definition)
    typed = SemanticCoverageResult.model_validate(response(key, "source"))
    runner = PublishedCoverageRunner(
        (definition,),
        model=lambda definition, key, bodies: validate_semantic_result(
            definition, key, bodies, typed
        ),
    )
    part = runner.run(key, {"part-1": "source"}, prior=())
    merged = runner.run(
        key.model_copy(update={"kind": "record_merge", "part_id": None, "part_digest": None}),
        {"part-1": "source"},
        prior=(part,),
    )
    assert merged.outcome == "finding"
    assert merged.part_result_digests == (part.digest,)
    assert merged.quotes == part.quotes


@pytest.mark.parametrize(
    "field,value",
    [
        ("record_id", "other"),
        ("content_digest", "c" * 64),
        ("check_id", "other"),
        ("check_version", "2"),
        ("definition_digest", "c" * 64),
        ("part_id", "other"),
        ("part_digest", "c" * 64),
    ],
)
def test_every_response_identity_field_must_match(field, value):
    key = unit(semantic_check("review-profile"))
    payload = response(key, "source", outcome="clear", categories=())
    payload["key"][field] = value
    with pytest.raises(CoverageRefusedError) as refused:
        run_review(payload)
    assert refused.value.reason == CoverageRefusalReason.UNSUPPORTED


def test_typed_result_cannot_bypass_validation_via_model_copy():
    key = unit(semantic_check("review-profile"))
    typed = SemanticCoverageResult.model_validate(response(key, "source"))
    forged = typed.model_copy(update={"outcome": "clear"})
    with pytest.raises(CoverageRefusedError):
        run_review(forged)


@pytest.mark.parametrize("location", ["result", "key", "quote"])
@pytest.mark.parametrize("injection", ["copy", "construct", "pydantic_extra"])
def test_typed_unknown_attributes_are_refused_before_serialization(location, injection):
    key = unit(semantic_check("review-profile"))
    payload = response(key, "source", outcome="clear", categories=())
    if location == "quote":
        payload = response(key, "source")
    typed = SemanticCoverageResult.model_validate(payload)
    target = {
        "result": typed,
        "key": typed.key,
        "quote": typed.quotes[0] if typed.quotes else None,
    }[location]
    extra = {"unknown": True} if location == "key" else {"confidence": 0.99}
    if injection == "copy":
        forged = target.model_copy(update=extra)
    else:
        forged = type(target).model_construct(**target.__dict__)
        if injection == "construct":
            forged.__dict__.update(extra)
        else:
            object.__setattr__(forged, "__pydantic_extra__", extra)
    if location == "result":
        typed = forged
    elif location == "key":
        typed = typed.model_copy(update={"key": forged})
    else:
        typed = typed.model_copy(update={"quotes": (forged,)})
    with pytest.raises(CoverageRefusedError) as refused:
        run_review(typed)
    assert refused.value.reason == CoverageRefusalReason.UNSUPPORTED


@pytest.mark.parametrize("outcome", ["finding", "clear"])
def test_valid_constructed_typed_result_still_works(outcome):
    key = unit(semantic_check("review-profile"))
    categories = CATEGORIES[:1] if outcome == "finding" else ()
    typed = SemanticCoverageResult.model_validate(
        response(key, "source", outcome=outcome, categories=categories)
    )
    constructed = SemanticCoverageResult.model_construct(**typed.__dict__)
    assert run_review(constructed) == run_review(typed)


@pytest.mark.parametrize("invalid", [b"finding", {"finding"}, object()])
def test_typed_invalid_field_types_are_refused(invalid):
    key = unit(semantic_check("review-profile"))
    typed = SemanticCoverageResult.model_validate(response(key, "source"))
    with pytest.raises(CoverageRefusedError) as refused:
        run_review(typed.model_copy(update={"outcome": invalid}))
    assert refused.value.reason == CoverageRefusalReason.UNSUPPORTED


def test_full_character_limit_is_supported_without_truncation():
    definition = semantic_check("review-profile")
    body = "字" * definition.max_part_characters
    key = unit(definition)
    payload = response(key, body, outcome="clear", categories=())
    seen = []

    def review(definition, key, bodies):
        seen.append(bodies)
        return validate_semantic_result(definition, key, bodies, payload)

    runner = PublishedCoverageRunner((definition,), model=review)
    assert runner.run(key, {"part-1": body}, prior=()).outcome == "clear"
    assert seen == [{"part-1": body}]


def test_runner_refuses_oversize_before_calling_model():
    definition = semantic_check("review-profile")

    def review(*args):
        raise AssertionError("oversize must be refused before invoking model")

    runner = PublishedCoverageRunner((definition,), model=review)
    with pytest.raises(CoverageRefusedError) as refused:
        runner.run(unit(definition), {"part-1": "x" * 12001}, prior=())
    assert refused.value.reason == CoverageRefusalReason.UNSUPPORTED
