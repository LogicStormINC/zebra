"""Independent socket consumer; uploaded Python is parsed but never executed."""

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from tests.api.test_bundle_management import write
from tests.api.test_bundle_management_process import row_counts
from tests.api.test_script_validation import GET, POST, configured_fixture
from tests.api.test_script_validation import ROOT as REPOSITORY

SERVER = """
import sys
import uvicorn
from dataclasses import replace
from tests.test_bundle_assembly import settings
from zebra_agent_api import create_http_app
from zebra_agent_config import ApiSettings
active = replace(settings(), database_url=sys.argv[1],
    api=ApiSettings(auth_token='unrelated-api-token'),
    script_validation_config=sys.argv[2])
uvicorn.run(create_http_app(settings=active), fd=int(sys.argv[3]),
    log_level='error', access_log=False)
"""
CONTRACT = REPOSITORY / "docs/contracts/script-validation-v1"


def test_independent_api_process_current_trust_vectors_and_preservation(tmp_path: Path):
    _, approval_path, approval, _, headers = configured_fixture(tmp_path)
    database = tmp_path / "state.sqlite"
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
                str(listener.fileno()),
            ],
            cwd=REPOSITORY,
            pass_fds=(listener.fileno(),),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        ) as process:
            try:
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{listener.getsockname()[1]}",
                    timeout=2,
                    trust_env=False,
                ) as client:
                    deadline = time.monotonic() + 15
                    while True:
                        assert process.poll() is None, process.stderr.read()
                        try:
                            discovery = client.get(GET, headers=headers)
                            break
                        except httpx.TransportError:
                            assert time.monotonic() < deadline, "owned API startup timeout"
                            time.sleep(0.02)
                    assert discovery.status_code == 200, discovery.text
                    assert discovery.json()["contract"] == json.loads(
                        (CONTRACT / "contract.json").read_bytes()
                    )
                    before = row_counts(database)
                    original_approval = approval_path.read_bytes()
                    post_headers = {**headers, "Content-Type": "application/json"}
                    for vector in json.loads((CONTRACT / "positive-vectors.json").read_bytes()):
                        response = client.post(POST, headers=post_headers, content=vector["raw"])
                        assert response.status_code == 200, response.text
                        for field in ("inputDigest", "manifestDigest", "sourceDigest"):
                            assert response.json()[field] == vector[field]
                    for vector in json.loads((CONTRACT / "negative-vectors.json").read_bytes()):
                        response = client.post(POST, headers=post_headers, content=vector["raw"])
                        assert response.status_code == vector["status"], vector["name"]
                    assert approval_path.read_bytes() == original_approval
                    write(approval_path, {**approval, "actions": ["script.contract.read"]})
                    assert client.get(GET, headers=headers).status_code == 200
                    assert client.post(POST, headers=post_headers, content="{}").status_code == 403
                    write(approval_path, {**approval, "credential_sha256": "0" * 64})
                    assert client.get(GET, headers=headers).status_code == 401
                    write(approval_path, approval)
                    assert client.get(GET, headers=headers).status_code == 200
                    assert row_counts(database) == before
                    assert not any("DO_NOT_ECHO" in p.name for p in tmp_path.iterdir())
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
