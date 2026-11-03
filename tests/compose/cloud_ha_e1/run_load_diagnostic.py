"""Exercise the E1 adapters against the isolated synthetic fixture."""

import argparse
import asyncio
import json
import ssl
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path

import httpx
from open_loop import run_offers
from signed_load import _record, recover_original, submit_once
from sse_load import StreamWindowError, hold_streams


async def run(args: argparse.Namespace) -> None:
    fixture = json.loads(args.fixture.read_text())
    task = json.loads(args.task.read_text())
    if not task.get("prompt", "").startswith("[zebra-ha-e1-short-v1]"):
        raise ValueError("expected the deterministic E1 task marker")
    if not task.get("workspace", "").startswith(
        "/var/lib/docker/volumes/zebra-ha-e1-20261102-workspaces/_data/"
    ):
        raise ValueError("expected an isolated E1 workspace")
    token = json.loads(args.principals.read_text())[0]["token"]
    args.output.mkdir(mode=0o700)
    tls = ssl.create_default_context(cafile=str(args.ca))
    async with (
        httpx.AsyncClient(verify=tls, trust_env=False, timeout=8) as admission,
        httpx.AsyncClient(
            verify=tls,
            trust_env=False,
            timeout=httpx.Timeout(30),
            limits=httpx.Limits(max_connections=args.streams + 4),
        ) as streams,
    ):

        async def submit(index: int) -> str:
            return await submit_once(
                admission, args.output, index=index, principal_token=token, task=task
            )

        rows = []
        offers = []
        try:
            stream_window = (
                hold_streams(
                    streams,
                    task_id=fixture["response"]["task_id"],
                    binding=fixture["binding"],
                    principal_token=token,
                    count=args.streams,
                )
                if args.streams
                else nullcontext([])
            )
            async with stream_window as rows:
                offers = await run_offers(
                    submit, rate=5, duration=args.seconds, max_inflight=16, request_timeout=12
                )
        except StreamWindowError as exc:
            rows = exc.rows
            raise
        finally:
            _record(
                args.output / "window.json",
                {"offers": [asdict(item) for item in offers], "streams": [asdict(r) for r in rows]},
            )
        recovered_count = 0
        for offer in offers:
            path = args.output / f"{offer.index}.intent.json"
            if path.exists():
                status, receipt, original = await recover_original(
                    admission, json.loads(path.read_text()), principal_token=token
                )
                _record(
                    args.output / f"{offer.index}.get.json", {"status": status, "receipt": receipt}
                )
                recovered_count += int(original is not None)
        if recovered_count != len(offers) or any(item.disposition != "accepted" for item in offers):
            raise RuntimeError("E1 diagnostic did not accept and recover every original offer")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("fixture", "task", "principals", "ca", "output"):
        parser.add_argument("--" + option, required=True, type=Path)
    parser.add_argument("--streams", type=int, choices=range(257), default=4)
    parser.add_argument("--seconds", type=int, choices=range(1, 4), default=1)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
