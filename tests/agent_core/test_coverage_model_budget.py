"""Small trust-boundary regressions for frozen reservation/strict usage values."""

import pytest
from agent_core.domain.coverage_model_budget import (
    CoverageModelReservation,
    CoverageModelUsageReceipt,
)
from agent_core.domain.coverage_validation import expected_units

from tests.agent_core.test_coverage_contracts import contract, records


def reservation():
    return CoverageModelReservation(
        reservation_key="call-1",
        admission_digest="a" * 64,
        key=expected_units(contract(), records())[0],
        request_digest="b" * 64,
        model_profile="review",
        token_bound=100,
    )


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "total_tokens"])
@pytest.mark.parametrize("value", [True, False, 1.0, None, "1", -1])
def test_receipt_rejects_nonexact_counts(field, value):
    data = dict(reservation=reservation(), input_tokens=1, output_tokens=2, total_tokens=3)
    data[field] = value
    with pytest.raises(ValueError):
        CoverageModelUsageReceipt.model_validate(data)


@pytest.mark.parametrize("counts", [(2, 2, 3), (1, 1, 101), (101, 0, 101)])
def test_receipt_must_cover_input_output_and_fit_reservation(counts):
    with pytest.raises(ValueError):
        CoverageModelUsageReceipt(
            reservation=reservation(),
            input_tokens=counts[0],
            output_tokens=counts[1],
            total_tokens=counts[2],
        )


def test_typed_forgery_and_unknown_attributes_are_revalidated():
    receipt = CoverageModelUsageReceipt(
        reservation=reservation(), input_tokens=1, output_tokens=2, total_tokens=3
    )
    with pytest.raises(ValueError):
        CoverageModelUsageReceipt.model_validate(receipt.model_copy(update={"total_tokens": True}))
    with pytest.raises(ValueError):
        CoverageModelUsageReceipt.model_validate(receipt.model_copy(update={"unknown": 1}))
    with pytest.raises(ValueError):
        CoverageModelReservation.model_validate(
            reservation().model_copy(update={"token_bound": False})
        )
    with pytest.raises(ValueError):
        receipt.total_tokens = 0


def test_receipt_allows_total_overhead_and_exact_zero_usage():
    assert (
        CoverageModelUsageReceipt(
            reservation=reservation(), input_tokens=1, output_tokens=2, total_tokens=4
        ).total_tokens
        == 4
    )
    assert (
        CoverageModelUsageReceipt(
            reservation=reservation(), input_tokens=0, output_tokens=0, total_tokens=0
        ).total_tokens
        == 0
    )
