"""Long-running checkpointed worker used by the Kubernetes gVisor drill."""

from __future__ import annotations

import os
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import urlopen


def main() -> None:
    state_path = Path(os.environ.get("ZEBRA_STATE_PATH", "/state/checkpoint"))
    target = int(os.environ.get("ZEBRA_TARGET_STEPS", "6"))
    api_url = os.environ.get("ZEBRA_API_URL", "http://api:8080/healthz")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    current = int(state_path.read_text(encoding="utf-8")) if state_path.exists() else 0
    print(f"WORKER_RESUMED_FROM={current}", flush=True)
    for step in range(current + 1, target + 1):
        with urlopen(api_url, timeout=3) as response:
            if response.status != 200:
                raise RuntimeError(f"API returned {response.status}")
        with NamedTemporaryFile(
            mode="w", dir=state_path.parent, prefix="checkpoint-", delete=False
        ) as temporary:
            temporary.write(str(step))
            temporary_path = Path(temporary.name)
        temporary_path.replace(state_path)
        print(f"WORKER_STEP={step} API_OK=1", flush=True)
        time.sleep(1.5)
    print("WORKER_RESULT=PASS", flush=True)


if __name__ == "__main__":
    main()
