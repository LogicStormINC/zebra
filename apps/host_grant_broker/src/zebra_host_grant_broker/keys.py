"""RSA key loading, JWKS export, and development keypair generation."""

from __future__ import annotations

import base64
import os
import re
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def load_private_key(pem: str) -> rsa.RSAPrivateKey:
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("Host Grant signing key must be an RSA private key")
    return key


def jwk_document(key: rsa.RSAPrivateKey, key_id: str) -> dict[str, str]:
    public = key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": key_id,
        "n": _base64url_uint(public.n),
        "e": _base64url_uint(public.e),
    }


def generate_keypair(out_dir: Path, key_id: str = "host-grant-v1") -> tuple[Path, Path]:
    """Write a fresh RSA keypair for deployment bootstrap; returns (private, public)."""

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", key_id):
        raise ValueError("key ID must be a bounded filename identifier")
    out_dir.mkdir(parents=True, exist_ok=True)
    private_path = out_dir / f"{key_id}.pem"
    public_path = out_dir / f"{key_id}.pub.jwks.json"
    if private_path.exists() or public_path.exists():
        raise FileExistsError("keypair already exists; explicit key rotation is required")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    import json

    public_bytes = (json.dumps({"keys": [jwk_document(key, key_id)]}, indent=2) + "\n").encode()
    created: list[Path] = []
    try:
        for path, content in ((private_path, private_bytes), (public_path, public_bytes)):
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append(path)
            with os.fdopen(descriptor, "wb") as output:
                output.write(content)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return private_path, public_path


def _base64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("secrets")
    kid = sys.argv[2] if len(sys.argv) > 2 else "host-grant-v1"
    private, public = generate_keypair(target, kid)
    print(f"private key: {private}")
    print(f"jwks:        {public}")
