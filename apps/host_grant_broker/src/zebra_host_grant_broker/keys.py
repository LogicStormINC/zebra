"""RSA key loading, JWKS export, and development keypair generation."""

from __future__ import annotations

import base64
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


def generate_keypair(out_dir: Path, key_id: str = "trench-host-grant-v1") -> tuple[Path, Path]:
    """Write a fresh RSA keypair for deployment bootstrap; returns (private, public)."""

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    out_dir.mkdir(parents=True, exist_ok=True)
    private_path = out_dir / f"{key_id}.pem"
    public_path = out_dir / f"{key_id}.pub.jwks.json"
    private_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    import json

    public_path.write_text(json.dumps({"keys": [jwk_document(key, key_id)]}, indent=2) + "\n")
    private_path.chmod(0o600)
    return private_path, public_path


def _base64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("secrets")
    kid = sys.argv[2] if len(sys.argv) > 2 else "trench-host-grant-v1"
    private, public = generate_keypair(target, kid)
    print(f"private key: {private}")
    print(f"jwks:        {public}")
