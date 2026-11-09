"""Offline checks: failed preparation cannot execute; receipt=1 stays bounded."""

import argparse
import ast
import asyncio
import json
import shlex
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import httpx
import signed_load


def check_preparation(legacy: bool) -> None:
    with TemporaryDirectory() as folder:
        root = Path(folder)
        prepared, executed = root / "prepared.py", root / "executed.py"
        marker = root / "task-post-marker"
        prepared.write_text(
            "raise ModuleNotFoundError('synthetic missing preparation dependency')\n"
        )
        executed.write_text(f"from pathlib import Path; Path({str(marker)!r}).touch()\n")
        if legacy:
            # Reproduce the observed unchecked shell boundary, without any network.
            command = [
                "sh",
                "-c",
                f"{shlex.quote(sys.executable)} {shlex.quote(str(prepared))}; "
                f"{shlex.quote(sys.executable)} {shlex.quote(str(executed))}",
            ]
        else:
            command = [
                sys.executable,
                str(Path(__file__).with_name("run_execution_measurement.py")),
                "--prepare",
                str(prepared),
                "--execute",
                str(executed),
                "--evidence",
                str(root),
            ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        assert "synthetic missing preparation dependency" in result.stderr
        assert not marker.exists(), "failed preparation still reached the Task issuing stage"
        assert result.returncode != 0
        prepared.write_text(
            'from pathlib import Path; Path(__import__("sys").argv[1], "prepared").touch()\n'
        )
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        assert result.returncode == 0 and marker.exists() and (root / "prepared").exists()


async def check_observer(fixture: Path) -> None:
    tree = ast.parse(fixture.read_text())
    node = next(
        n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "read_original"
    )
    namespace = {"receipt_lock": asyncio.Lock(), "signed_load": signed_load, "token": "offline"}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(fixture), "exec"), namespace)
    active = peak = calls = 0
    task_posts = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak, calls
        if str(request.url) == signed_load._BROKER:
            return httpx.Response(200, json={"grant": "offline"})
        if request.method != "GET":
            task_posts.append(request.url.path)
            raise AssertionError("observer must never replay a Task POST")
        active += 1
        peak = max(peak, active)
        calls += 1
        try:
            await asyncio.sleep(0.002)
            return httpx.Response(503, json={"error": {"code": "capacity_unavailable"}})
        finally:
            active -= 1

    intent = {"operation": str(uuid4()), "payload": {}, "key": "00" * 32, "binding": {}}
    with TemporaryDirectory() as folder:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            results = await asyncio.gather(
                *(namespace["read_original"](client, intent) for _ in range(16))
            )
            for index, (status, receipt, opened) in enumerate(results):
                signed_load._record(
                    Path(folder) / f"{index}.get.json",
                    {"status": status, "receipt": receipt, "opened": opened is not None},
                )
            saved = [json.loads(p.read_text()) for p in Path(folder).glob("*.get.json")]
    assert peak == 1 and calls == 16 and not task_posts
    assert len(saved) == 16 and all(v["status"] == 503 and not v["opened"] for v in saved)
    assert not namespace["receipt_lock"].locked()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--legacy", action="store_true")
    args = parser.parse_args()
    check_preparation(args.legacy)
    asyncio.run(check_observer(args.fixture))
    print(
        "PASS: preparation failure halts, success ordered, receipt peak=1, "
        "16 raw503 retained, noTaskPOST"
    )


if __name__ == "__main__":
    main()
