import hashlib
from pathlib import Path

import pytest
from agent_security import (
    SetupDownload,
    SetupEgressError,
    SetupEgressGateway,
    TemporarySetupCredential,
)


def _download(payload: bytes = b"wheel") -> SetupDownload:
    return SetupDownload(
        url="https://files.example.test/package.whl",
        sha256=hashlib.sha256(payload).hexdigest(),
        file_name="package.whl",
    )


def test_setup_egress_is_exact_hash_verified_cached_and_revocable(tmp_path: Path) -> None:
    calls: list[tuple[str, str | None]] = []
    credential = TemporarySetupCredential("temporary-secret")

    def transport(url: str, *, authorization: str | None, max_bytes: int) -> bytes:
        assert max_bytes > 0
        calls.append((url, authorization))
        return b"wheel"

    gateway = SetupEgressGateway(
        allowed_domains=("files.example.test",),
        cache_root=tmp_path,
        credential=credential,
        transport=transport,
    )

    first = gateway.materialize(_download())
    second = gateway.materialize(_download())
    gateway.close()

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert calls == [("https://files.example.test/package.whl", "Bearer temporary-secret")]
    assert credential.revoked is True
    assert "temporary-secret" not in repr(credential)
    assert "temporary-secret" not in repr(first)
    with pytest.raises(SetupEgressError, match="closed"):
        gateway.materialize(_download())


@pytest.mark.parametrize(
    "url",
    [
        "http://files.example.test/package.whl",
        "https://other.example.test/package.whl",
        "https://127.0.0.1/package.whl",
        "https://user:secret@files.example.test/package.whl",
        "https://files.example.test/package.whl?token=secret",
        "https://files.example.test:8443/package.whl",
    ],
)
def test_setup_egress_rejects_unscoped_targets(tmp_path: Path, url: str) -> None:
    dependency = SetupDownload(
        url=url,
        sha256=hashlib.sha256(b"wheel").hexdigest(),
        file_name="package.whl",
    )
    gateway = SetupEgressGateway(
        allowed_domains=("files.example.test",),
        cache_root=tmp_path,
        transport=lambda *args, **kwargs: b"wheel",
    )

    with pytest.raises((SetupEgressError, ValueError)):
        gateway.materialize(dependency)


def test_setup_egress_rejects_integrity_mismatch_and_revoked_credential(
    tmp_path: Path,
) -> None:
    credential = TemporarySetupCredential("temporary-secret")
    gateway = SetupEgressGateway(
        allowed_domains=("files.example.test",),
        cache_root=tmp_path,
        credential=credential,
        transport=lambda *args, **kwargs: b"tampered",
    )

    with pytest.raises(SetupEgressError, match="sha256 mismatch"):
        gateway.materialize(_download())
    gateway.close()
    with pytest.raises(SetupEgressError, match="revoked"):
        credential.authorization_header()
