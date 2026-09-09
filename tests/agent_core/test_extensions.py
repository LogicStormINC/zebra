import pytest
from agent_core.domain.extension_snapshots import (
    ExtensionPermissions,
    ExtensionSnapshot,
    McpSnapshotEntry,
)
from agent_core.domain.extensions import (
    ExtensionScope,
    McpConnection,
    SkillInstallation,
    SkillVersion,
)
from agent_core.ports.extensions import (
    ExtensionPageRequest,
    McpConnectionPage,
    SkillInstallationPage,
)
from pydantic import ValidationError


def scope(**changes: str) -> ExtensionScope:
    return ExtensionScope.model_validate(
        dict(
            authority_issuer="issuer",
            namespace_id="ns",
            principal_id="user",
            workspace_id="workspace",
        )
        | changes
    )


def connection(**changes: object) -> McpConnection:
    return McpConnection.model_validate(
        dict(scope=scope(), connection_id="mcp", revision=1, endpoint="https://example.com/mcp")
        | changes
    )


def test_scope_is_opaque_frozen_and_complete() -> None:
    assert scope().principal_id == "user"
    for field in ("authority_issuer", "namespace_id", "principal_id", "workspace_id"):
        with pytest.raises(ValidationError):
            scope(**{field: " "})
        assert scope() != scope(**{field: "other"})
    with pytest.raises(ValidationError):
        scope().workspace_id = "other"


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.com",
        "file:///tmp/mcp",
        "https://user:pass@example.com",
        "https://example.com/#x",
        "https://example.com/\n",
        "https://example.com:bad",
        "https://",
        "https://example.com/#",
    ],
)
def test_endpoint_rejects_unsafe_syntax(endpoint: str) -> None:
    with pytest.raises(ValidationError):
        connection(endpoint=endpoint)


@pytest.mark.parametrize(
    "field", ["command", "args", "env", "headers", "credentials", "allow_private_http"]
)
def test_connection_forbids_local_transport_and_secrets(field: str) -> None:
    with pytest.raises(ValidationError):
        connection(**{field: "secret"})
    with pytest.raises(ValidationError):
        connection(transport="stdio")


@pytest.mark.parametrize("revision", [True, 0, -1, "1", 1.2])
def test_revision_is_strict_positive_integer(revision: object) -> None:
    with pytest.raises(ValidationError):
        connection(revision=revision)


def test_auth_requires_reference_and_never_implies_execution_permission() -> None:
    with pytest.raises(ValidationError):
        connection(auth_mode="bearer", auth_state="ready")
    assert connection(
        auth_mode="bearer", auth_state="ready", credential_ref="vault:opaque"
    ).credential_ref
    assert ExtensionPermissions().tools == ()


def test_fixed_skill_version_digest_and_scope() -> None:
    version = SkillVersion(
        skill_id="skill", version_id="v1", artifact_ref="artifact://one", content_digest="a" * 64
    )
    install = SkillInstallation(scope=scope(), installation_id="i", revision=1, version=version)
    assert install.enabled
    with pytest.raises(ValidationError):
        SkillVersion.model_validate(version.model_dump() | {"content_digest": "z" * 64})
    with pytest.raises(ValidationError):
        ExtensionSnapshot(
            scope=scope(workspace_id="other"), session_id="s", turn_id="t", skills=(install,)
        )


def test_permissions_narrow_and_canonical_digest() -> None:
    grant = ExtensionPermissions(tools=("b", "a"), resources=("r",))
    requested = ExtensionPermissions(tools=("a", "extra"), prompts=("p",))
    assert grant.narrow(requested) == ExtensionPermissions(tools=("a",))
    assert not requested.is_subset_of(grant)
    entry = McpSnapshotEntry(connection=connection(), catalog_digest="b" * 64, permissions=grant)
    snapshot = ExtensionSnapshot(scope=scope(), session_id="s", turn_id="t", mcp=(entry,))
    reversed_entry = McpSnapshotEntry(
        connection=connection(),
        catalog_digest="b" * 64,
        permissions=ExtensionPermissions(tools=("a", "b"), resources=("r",)),
    )
    equivalent = ExtensionSnapshot(
        scope=scope(), session_id="s", turn_id="t", mcp=(reversed_entry,)
    )
    assert equivalent.digest == snapshot.digest
    subset_entry = McpSnapshotEntry(
        connection=connection(), catalog_digest="b" * 64, permissions=grant.narrow(requested)
    )
    subset = ExtensionSnapshot(scope=scope(), session_id="s", turn_id="t", mcp=(subset_entry,))
    assert subset.is_subset_of(snapshot)
    assert not snapshot.is_subset_of(subset)
    changed = ExtensionSnapshot(scope=scope(), session_id="s", turn_id="other", mcp=(entry,))
    assert not changed.is_subset_of(snapshot)
    with pytest.raises(ValidationError):
        ExtensionSnapshot(scope=scope(), session_id="s", turn_id="t", mcp=(entry, entry))
    with pytest.raises(ValidationError):
        ExtensionPermissions(tools=("a", "a"))


@pytest.mark.parametrize(
    "field", ["authority_issuer", "namespace_id", "principal_id", "workspace_id"]
)
def test_snapshot_rejects_every_scope_mismatch(field: str) -> None:
    entry = McpSnapshotEntry(connection=connection(), catalog_digest="a" * 64)
    with pytest.raises(ValidationError, match="exact extension scope"):
        ExtensionSnapshot(
            scope=scope(**{field: "other"}), session_id="s", turn_id="t", mcp=(entry,)
        )


def test_snapshot_is_deeply_frozen_and_config_catalog_pins_cannot_expand() -> None:
    entry = McpSnapshotEntry(connection=connection(), catalog_digest="a" * 64)
    snapshot = ExtensionSnapshot(scope=scope(), session_id="s", turn_id="t", mcp=[entry])
    assert isinstance(snapshot.mcp, tuple)
    with pytest.raises(ValidationError):
        snapshot.mcp[0].connection.endpoint = "https://other.example.com"
    for replacement in (
        McpSnapshotEntry(connection=connection(revision=2), catalog_digest="a" * 64),
        McpSnapshotEntry(connection=connection(), catalog_digest="b" * 64),
    ):
        changed = ExtensionSnapshot(scope=scope(), session_id="s", turn_id="t", mcp=(replacement,))
        assert not changed.is_subset_of(snapshot)
        assert changed.digest != snapshot.digest
    for changes in (
        {"enabled": False},
        {"auth_mode": "bearer", "auth_state": "pending"},
        {"auth_mode": "bearer", "auth_state": "expired"},
        {"auth_mode": "bearer", "auth_state": "revoked"},
    ):
        unavailable = connection(**changes)
        with pytest.raises(ValidationError, match="enabled and authentication usable"):
            McpSnapshotEntry(connection=unavailable, catalog_digest="a" * 64)


@pytest.mark.parametrize("mode", ["bearer", "api_key", "oauth"])
def test_auth_mode_state_matrix(mode: str) -> None:
    for state in ("pending", "expired", "revoked"):
        assert connection(auth_mode=mode, auth_state=state)
        assert connection(auth_mode=mode, auth_state=state, credential_ref="vault:ref")
    assert connection(auth_mode=mode, auth_state="ready", credential_ref="vault:ref")
    with pytest.raises(ValidationError):
        connection(auth_mode=mode)
    with pytest.raises(ValidationError):
        connection(auth_mode=mode, auth_state="ready")
    for state in ("pending", "ready", "expired", "revoked"):
        with pytest.raises(ValidationError):
            connection(auth_mode="none", auth_state=state)
    with pytest.raises(ValidationError):
        connection(credential_ref="vault:ref")


def test_payload_size_and_control_boundaries() -> None:
    assert connection(connection_id="a" * 512)
    for value in ("a" * 513, "a\x00b", "a\x7fb", "a\tb"):
        with pytest.raises(ValidationError):
            connection(connection_id=value)
    with pytest.raises(ValidationError):
        connection(endpoint="https://example.com/" + "a" * 2048)
    for field in ("tools", "resources", "prompts"):
        assert ExtensionPermissions.model_validate({field: [str(i) for i in range(256)]})
        with pytest.raises(ValidationError):
            ExtensionPermissions.model_validate({field: [str(i) for i in range(257)]})
    entries = tuple(
        McpSnapshotEntry(connection=connection(connection_id=str(i)), catalog_digest="a" * 64)
        for i in range(33)
    )
    assert ExtensionSnapshot(scope=scope(), session_id="s", turn_id="t", mcp=entries[:32])
    with pytest.raises(ValidationError):
        ExtensionSnapshot(scope=scope(), session_id="s", turn_id="t", mcp=entries)
    installs = tuple(
        SkillInstallation(
            scope=scope(),
            installation_id=str(i),
            revision=1,
            version=SkillVersion(
                skill_id=str(i),
                version_id="v1",
                artifact_ref="artifact://x",
                content_digest="a" * 64,
            ),
        )
        for i in range(33)
    )
    with pytest.raises(ValidationError):
        ExtensionSnapshot(scope=scope(), session_id="s", turn_id="t", skills=installs)
    for field in ("token", "api_key", "client_secret", "access_token", "raw_headers"):
        with pytest.raises(ValidationError):
            connection(**{field: "secret"})


def test_bounded_pagination_contract() -> None:
    assert ExtensionPageRequest(limit=100, cursor="opaque").cursor == "opaque"
    assert SkillInstallationPage(items=()).next_cursor is None
    assert McpConnectionPage(items=()).next_cursor is None
    for limit in (0, 101, True, "5", 1.5):
        with pytest.raises(ValidationError):
            ExtensionPageRequest.model_validate({"limit": limit})
    for cursor in ("", "a" * 513, "x\ny"):
        with pytest.raises(ValidationError):
            ExtensionPageRequest(cursor=cursor)
    with pytest.raises(ValidationError):
        McpConnectionPage(items=(connection(),) * 101)
