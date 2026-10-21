"""Private validation authority and execution compatibility boundaries."""

from dataclasses import replace
from pathlib import Path

from zebra_agent_config import ApiSettings, load_settings
from zebra_agent_config.bundle_settings import baseline_digest

from tests.test_bundle_assembly import settings


def test_api_only_path_preserves_published_baseline_digest(tmp_path: Path) -> None:
    configured = load_settings({"ZEBRA_BUNDLE_MANAGEMENT_CONFIG": str(tmp_path / "approval.json")})
    assert getattr(configured, "bundle_management_config", None) == str(tmp_path / "approval.json")
    expected = "sha256:c7748ed8d32a5c534d4c7c8290fd71f5d5d3c01d46c3d38c53665a5cce900fdc"
    original = settings()
    assert baseline_digest(original, "ab" * 32) == expected
    assert (
        baseline_digest(
            replace(original, bundle_management_config=str(tmp_path / "approval.json")), "ab" * 32
        )
        == expected
    )
    assert (
        baseline_digest(replace(original, api=ApiSettings(auth_token="changed")), "ab" * 32)
        != expected
    )


def test_execution_catalog_requires_private_regular_bounded_file(tmp_path: Path) -> None:
    import os

    import pytest
    from zebra_agent_config.bundle_settings import load_execution_catalog

    from tests.test_bundle_assembly import write_catalog

    _, configured, _ = write_catalog(tmp_path, settings())
    path = Path(configured.runtime_bundle_config)
    for mode in (0o644, 0o200, 0o000):
        path.chmod(mode)
        with pytest.raises(ValueError, match="^INVALID_EXECUTION_CATALOG$"):
            load_execution_catalog(str(path))
    path.chmod(0o400)
    assert load_execution_catalog(str(path)).scope.namespace_id == "tenant/example"
    path.unlink()
    os.mkfifo(path, 0o600)
    with pytest.raises(ValueError, match="^INVALID_EXECUTION_CATALOG$"):
        load_execution_catalog(str(path))


def test_private_approval_strict_fields_and_json_profile(tmp_path: Path) -> None:
    import copy
    import json
    import os

    import pytest
    from zebra_agent_api.bundle_management_config import load_bundle_management_approval

    from tests.api.test_bundle_management import configured_fixture, write

    _, path, value, _, _ = configured_fixture(tmp_path)
    assert load_bundle_management_approval(str(path), "local").scope.namespace_id == "local"
    assert "credential_sha256" not in repr(load_bundle_management_approval(str(path), "local"))
    bad_values = [
        {"unknown": True},
        {"schema_version": "future"},
        {"scope": {}},
        {"audience": ""},
        {"audience": "a" * 257},
        {"trust_revision": True},
        {"trust_revision": 0},
        {"trust_revision": 2**53},
        {"credential_sha256": "AB" * 32},
        {"credential_sha256": "secret"},
        {"expires_at": "2099-01-01"},
        {"expires_at": "2099-01-01T00:00:00+00:00"},
        {"expires_at": "2099-01-01T00:00:00+01:00Z"},
        {"expires_at": "2099-02-31T00:00:00Z"},
        {"expires_at": None},
        {"actions": []},
        {"actions": ["bundle.validate", "bundle.validate"]},
        {"actions": ["target.describe"]},
        {"actions": ["bundle.publish"]},
    ]
    for mutation in bad_values:
        write(path, {**value, **mutation})
        with pytest.raises(ValueError, match="^INVALID_BUNDLE_MANAGEMENT_APPROVAL$"):
            load_bundle_management_approval(str(path), "local")
    for field in value:
        absent = copy.deepcopy(value)
        del absent[field]
        write(path, absent)
        with pytest.raises(ValueError, match="^INVALID_BUNDLE_MANAGEMENT_APPROVAL$"):
            load_bundle_management_approval(str(path), "local")
    write(path, value)
    for namespace in (None, "other"):
        with pytest.raises(ValueError, match="^INVALID_BUNDLE_MANAGEMENT_APPROVAL$"):
            load_bundle_management_approval(str(path), namespace)
    for mode in (0o644, 0o200, 0o000):
        path.chmod(mode)
        with pytest.raises(ValueError, match="^INVALID_BUNDLE_MANAGEMENT_APPROVAL$"):
            load_bundle_management_approval(str(path), "local")
    path.chmod(0o400)
    assert load_bundle_management_approval(str(path), "local").trust_revision == 1
    path.chmod(0o600)
    raw = json.dumps(value).encode()
    for hostile in (
        b'{"actions":[],"actions":[]}',
        b" " * 16385,
        b"\xef\xbb\xbf" + raw,
        b'{"x":NaN}',
        b'{"x":1.0}',
        b'{"x":"\\ud800"}',
        b"[" * 30 + b"0" + b"]" * 30,
        b'{"x":9223372036854775808}',
    ):
        path.write_bytes(hostile)
        with pytest.raises(ValueError, match="^INVALID_BUNDLE_MANAGEMENT_APPROVAL$"):
            load_bundle_management_approval(str(path), "local")
    path.unlink()
    os.mkfifo(path, 0o600)
    with pytest.raises(ValueError, match="^INVALID_BUNDLE_MANAGEMENT_APPROVAL$"):
        load_bundle_management_approval(str(path), "local")
    path.unlink()
    path.mkdir()
    with pytest.raises(ValueError, match="^INVALID_BUNDLE_MANAGEMENT_APPROVAL$"):
        load_bundle_management_approval(str(path), "local")
    for missing in (None, "relative.json", str(tmp_path / "missing.json")):
        with pytest.raises(ValueError, match="^INVALID_BUNDLE_MANAGEMENT_APPROVAL$"):
            load_bundle_management_approval(missing, "local")


def test_catalog_relative_paths_remain_supported(tmp_path: Path, monkeypatch) -> None:
    from zebra_agent_config.bundle_settings import load_execution_catalog

    from tests.test_bundle_assembly import write_catalog

    _, _, _ = write_catalog(tmp_path, settings())
    monkeypatch.chdir(tmp_path)
    assert load_execution_catalog("execution-catalog.json").scope.namespace_id == "tenant/example"
