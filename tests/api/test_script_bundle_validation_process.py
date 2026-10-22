"""Independent socket API consumer: pure observations and live private revocation."""

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from tests.api.test_bundle_management import write
from tests.api.test_bundle_management_process import ROOT, SERVER, row_counts
from tests.api.test_script_bundle_validation import GET, POST, configured_fixture


def test_socket_process_validates_without_execution_or_rows(tmp_path: Path):
    cfg, approval_path, approval, value, headers = configured_fixture(tmp_path)
    database = tmp_path / "owned.sqlite"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with subprocess.Popen(
            [
                sys.executable,
                "-c",
                SERVER,
                str(database),
                str(approval_path),
                cfg.runtime_bundle_config,
                str(listener.fileno()),
            ],
            cwd=ROOT,
            pass_fds=(listener.fileno(),),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        ) as process:
            try:
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{listener.getsockname()[1]}",
                    timeout=3,
                    trust_env=False,
                ) as client:
                    deadline = time.monotonic() + 15
                    while True:
                        assert process.poll() is None, "owned native API exited"
                        try:
                            discovery = client.get(GET, headers=headers)
                            break
                        except httpx.TransportError:
                            assert time.monotonic() < deadline, "owned API startup timeout"
                            time.sleep(0.02)
                    assert discovery.status_code == 200, discovery.text
                    contract = json.loads(
                        (
                            ROOT / "docs/contracts/script-bundle-validation/contract.json"
                        ).read_bytes()
                    )
                    assert discovery.json()["contract"] == contract
                    before = row_counts(database)
                    catalog = Path(cfg.runtime_bundle_config).read_bytes()
                    raw = json.dumps(value, indent=1).encode()
                    first = client.post(POST, headers=headers, content=raw)
                    assert first.status_code == 200, first.text
                    assert first.json()["scriptBundleDigest"] == value["bundle_digest"]
                    assert (
                        client.post(POST, headers=headers, content=raw).json()["assemblyDigest"]
                        == first.json()["assemblyDigest"]
                    )
                    write(approval_path, approval | {"actions": ["script-bundle.contract.read"]})
                    assert client.get(GET, headers=headers).status_code == 200
                    assert client.post(POST, headers=headers, content=raw).status_code == 403
                    write(approval_path, approval | {"credential_sha256": "0" * 64})
                    assert client.get(GET, headers=headers).status_code == 401
                    write(approval_path, approval)
                    assert client.post(POST, headers=headers, content=raw).status_code == 200
                    assert row_counts(database) == before
                    assert Path(cfg.runtime_bundle_config).read_bytes() == catalog
                    assert not (tmp_path / "MUST_NOT_EXECUTE").exists()
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            error = process.stderr.read()
            assert "MUST_NOT_EXECUTE" not in error and headers["Authorization"] not in error
