import pytest
from agent_core.domain.skill_publications import SkillPublication
from agent_tools.skill_publications import _candidate

from tests.agent_tools.test_skill_publications import SCOPE, archive


def test_identity_and_frozen_bounded_metadata() -> None:
    record = _candidate(archive(version=""), SCOPE, "test")
    assert record.version_label == record.version.content_digest
    assert record.version.artifact_ref == f"artifact://{record.expectation.artifact_id}"
    assert "content" not in record.manifest[0].model_dump()
    with pytest.raises(ValueError):
        record.name = "changed"
    for updates in ({"state": "ready"}, {"name": "x" * 65}, {"manifest": ()},
                    {"description": "x" * 1025}, {"version_label": "x" * 65}):
        with pytest.raises(ValueError):
            SkillPublication.model_validate({**record.model_dump(), **updates})


@pytest.mark.parametrize("field", ["authority_issuer", "namespace_id", "principal_id",
                                   "workspace_id", "deployment"])
def test_object_identity_isolates_all_five_coordinates(field: str) -> None:
    data = archive()
    one = _candidate(data, SCOPE, "test")
    two = _candidate(data, SCOPE if field == "deployment" else
                     SCOPE.model_copy(update={field: "different"}),
                     "different" if field == "deployment" else "test")
    assert one.expectation.artifact_id != two.expectation.artifact_id
    assert one.version.skill_id == two.version.skill_id
    assert one.version.version_id == two.version.version_id
