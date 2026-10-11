"""Seed guard tests do not stand in for real provider/Host receipt verification."""

import pytest
from joint_business_seed import SEED, validate_seed
from support import E2EError


def test_seed_script_compiles_and_validates_scope_before_transaction():
    compile(SEED, "qa_native_business_seed", "exec")
    assert SEED.index("assert os.environ['DATABASE_URL']") < SEED.index(
        "async_sessionmaker(engine)()"
    )
    assert "ended_at=None" in SEED and "rate=12 if source_index==0 else 8" in SEED
    assert "source_type='feed'" not in SEED
    assert SEED.count("source_type='custom_subscription'") == 2
    assert "_event_payload(row)" in SEED


def test_seed_evidence_cannot_claim_partial_or_fake_data_complete():
    data = {
        "scope": "actual_scratch_business_rows",
        "provider_or_receipt_injection": False,
        "event_count": 48,
        "per_source_count": 24,
        "source_ids": ["a", "b"],
        "event_ids": [str(i) for i in range(48)],
    }
    validate_seed(data)
    for key, value in (
        ("provider_or_receipt_injection", True),
        ("event_count", 20),
        ("source_ids", ["a", "a"]),
    ):
        with pytest.raises(E2EError):
            validate_seed({**data, key: value})
