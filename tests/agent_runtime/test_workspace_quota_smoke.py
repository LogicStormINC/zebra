import errno
import json
import os
from pathlib import Path

import pytest
from agent_runtime import require_workspace_quota


def test_real_workspace_quota_reaches_enospc() -> None:
    raw_root = os.environ.get("ZEBRA_QUOTA_SMOKE_ROOT")
    if not raw_root:
        pytest.skip("set ZEBRA_QUOTA_SMOKE_ROOT to a dedicated limited mount")
    root = Path(raw_root).resolve(strict=True)
    evidence = require_workspace_quota(root, maximum_bytes=8 * 1024 * 1024)
    payload = b"x" * (1024 * 1024)
    target = root / "quota-fill.bin"
    exhausted = False
    try:
        with target.open("wb", buffering=0) as stream:
            while True:
                stream.write(payload)
    except OSError as exc:
        exhausted = exc.errno == errno.ENOSPC
        if not exhausted:
            raise
    finally:
        target.unlink(missing_ok=True)
    assert exhausted
    output = os.environ.get("ZEBRA_RUNTIME_EVIDENCE_PATH")
    if output:
        Path(output).write_text(
            json.dumps({**evidence.__dict__, "enospc_observed": True}, sort_keys=True),
            encoding="utf-8",
        )
