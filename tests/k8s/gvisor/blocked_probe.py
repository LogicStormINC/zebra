"""Probe that must be denied by the namespace NetworkPolicy."""

from urllib.error import URLError
from urllib.request import urlopen

try:
    with urlopen("http://api:8080/healthz", timeout=4) as response:
        print(f"BLOCKED_PROBE_UNEXPECTED_ALLOWED={response.status}")
except (TimeoutError, URLError, OSError):
    print("BLOCKED_PROBE=PASS")
else:
    raise SystemExit(1)
