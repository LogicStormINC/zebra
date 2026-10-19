"""Immutable package and binding facts must agree before persistence."""

import pytest

from tests.agent_storage.test_postgres_plugin_installations import SCOPE, _record


def test_installation_rejects_cross_scope_or_incomplete_bindings() -> None:
    original = _record()
    values = original.model_dump()
    for bindings in ([], [*values["bindings"], *values["bindings"]]):
        with pytest.raises(ValueError):
            type(original).model_validate({**values, "bindings": bindings})
    values["bindings"][0]["connection"]["scope"] = SCOPE.model_copy(
        update={"namespace_id": "other"}
    )
    with pytest.raises(ValueError, match="another scope"):
        type(original).model_validate(values)


def test_package_digest_covers_index_and_manifest() -> None:
    original = _record()
    values = original.model_dump()
    values["package"]["package_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="package digest"):
        type(original).model_validate(values)
