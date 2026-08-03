from uuid import uuid4

import pytest
from agent_core.domain import OpaqueAuthorityScope
from pydantic import ValidationError


def test_scope_preserves_opaque_identity_and_canonicalizes_session_ids() -> None:
    session_id = uuid4()

    scope = OpaqueAuthorityScope(
        authority_issuer="https://business.example.com",
        namespace_id="opaque-scope-01",
        allowed_session_ids=(str(session_id).upper(),),
    )

    assert scope.scope_key == ("https://business.example.com", "opaque-scope-01")
    assert scope.allowed_session_ids == (str(session_id),)
    assert not scope.is_full_namespace
    assert not scope.is_deny_all
    assert scope.allows_session(session_id)


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"authority_issuer": " ", "namespace_id": "scope"}, "non-blank"),
        ({"authority_issuer": "issuer", "namespace_id": " scope"}, "trimmed"),
        (
            {
                "authority_issuer": "issuer",
                "namespace_id": "scope",
                "allowed_session_ids": [str(uuid4()), str(uuid4())],
                "tenant_id": "must-not-be-modeled",
            },
            "extra",
        ),
        (
            {
                "authority_issuer": "issuer",
                "namespace_id": "scope",
                "allowed_session_ids": ["not-a-uuid"],
            },
            "UUID",
        ),
    ],
)
def test_scope_rejects_untrusted_or_business_fields(
    values: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        OpaqueAuthorityScope.model_validate(values)


def test_scope_rejects_duplicate_canonical_session_ids() -> None:
    session_id = str(uuid4())

    with pytest.raises(ValidationError, match="duplicates"):
        OpaqueAuthorityScope(
            authority_issuer="issuer",
            namespace_id="scope",
            allowed_session_ids=(session_id, session_id.upper()),
        )


def test_scope_distinguishes_full_namespace_from_explicit_deny_all() -> None:
    full = OpaqueAuthorityScope(authority_issuer="issuer", namespace_id="scope")
    deny_all = OpaqueAuthorityScope(
        authority_issuer="issuer",
        namespace_id="scope",
        allowed_session_ids=(),
    )
    session_id = uuid4()

    assert full.is_full_namespace
    assert full.allows_session(session_id)
    assert deny_all.is_deny_all
    assert not deny_all.allows_session(session_id)


def test_scope_rejects_session_allow_list_over_the_shared_bound() -> None:
    with pytest.raises(ValidationError, match="at most 20"):
        OpaqueAuthorityScope(
            authority_issuer="issuer",
            namespace_id="scope",
            allowed_session_ids=tuple(str(uuid4()) for _ in range(21)),
        )


def test_scope_requires_valid_session_argument_when_checking_membership() -> None:
    scope = OpaqueAuthorityScope(
        authority_issuer="issuer",
        namespace_id="scope",
        allowed_session_ids=(str(uuid4()),),
    )

    with pytest.raises(ValueError, match="session_id must be a UUID"):
        scope.allows_session("not-a-uuid")
