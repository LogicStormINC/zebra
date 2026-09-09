"""Exact HTTPS Host Grant origin parsing shared by startup and request checks."""

from urllib.parse import urlsplit


def _normalize_exact_origin(value: str) -> str:
    normalized = value.strip()
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Host Grant origins must be exact HTTPS origins")
    host = parsed.hostname
    if host is None:
        raise ValueError("Host Grant origin must contain a host")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Host Grant origin has an invalid port") from exc
    return f"https://{host.lower()}{f':{port}' if port is not None else ''}"
