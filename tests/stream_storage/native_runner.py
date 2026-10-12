"""CLI and secret-free Native measurement artifacts."""

import argparse
import asyncio
import hashlib
import json
import math
import os
import statistics
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

import psycopg

from tests.stream_storage.native_baseline import workload
from tests.stream_storage.native_environment import native_environment


def harness_hashes():
    return {
        file.name: hashlib.sha256(file.read_bytes()).hexdigest()
        for file in sorted(Path(__file__).parent.glob("*.py"))
    }


def summarize(cases):
    grouped = {}
    for case in cases:
        key = "/".join(str(case[k]) for k in ("reader", "hint", "scenario", "runs"))
        sql = sum(value for name, value in case["client"]["calls"].items() if "/sql:" in name)
        grouped.setdefault(key, []).append(sql)
    return {
        key: {
            "repetitions": len(values),
            "sql_min": min(values),
            "sql_max": max(values),
            "sql_median": statistics.median(values),
        }
        for key, values in grouped.items()
    }


async def main(args):
    dsn = os.environ.get("ZEBRA_STREAM_TEST_POSTGRES_DSN")
    redis_url = os.environ.get("ZEBRA_STREAM_TEST_REDIS_URL")
    build = None
    cases = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "mode": "v1-native",
        "build": build,
        "generated_at": datetime.now(UTC).isoformat(),
        "measurement_boundary": "native storage-backed reader and recorder seams",
        "not_measured": [
            "HTTP signed Grant admission/revalidation",
            "provider callback",
            "SDK render/first-character p95",
            "worker progress-coordinator cost",
            "10-minute idle Gate",
            "v2 comparison",
            "deployment acceptance",
        ],
        "counting": {
            "sql": "client execute/executemany calls; nested cursor counted once",
            "server": "pg_stat_statements.track=all; excludes statistics/WAL observer queries",
            "sockets": "successful libpq connection creation; includes bounded Task IO",
            "checkout": "connect/connect_task_io adapter requests; nested delegation counted once",
            "wal": "cluster-global WAL insert-LSN diagnostic; may include other test work",
            "latency": "synthetic batch recorder commit plus checkpoint; not delivery p95",
            "redis": "owned prefix memory, cumulative cases; never FLUSHDB",
        },
        "parameters": vars(args) | {"output": str(args.output)},
        "expected_cases": (
            args.repeats
            * len(args.sizes)
            * len(args.readers)
            * len(args.hints)
            * len(args.scenarios)
        ),
        "execution_status": "running",
        "harness_sha256_start": harness_hashes(),
        "cases": cases,
    }
    try:
        if not dsn or not redis_url:
            raise ValueError("set private ZEBRA_STREAM_TEST_POSTGRES_DSN and REDIS_URL")
        report["build"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        with native_environment(dsn, redis_url) as (scratch, client, fanout):
            with psycopg.connect(scratch) as connection:
                report["native_versions"] = {
                    "postgres": connection.execute("SHOW server_version").fetchone()[0],
                    "pg_stat_statements_track": connection.execute(
                        "SHOW pg_stat_statements.track"
                    ).fetchone()[0],
                    "redis": client.info("server")["redis_version"],
                }
            for repeat in range(args.repeats):
                for count in args.sizes:
                    for reader in args.readers:
                        for hint in args.hints:
                            for scenario in args.scenarios:
                                case = await workload(
                                    scratch,
                                    client,
                                    fanout,
                                    reader=reader,
                                    hint=hint,
                                    scenario=scenario,
                                    count=count,
                                    seconds=args.seconds,
                                    cadence=args.cadence,
                                    pool=args.pool == "production",
                                )
                                case["repeat"] = repeat + 1
                                cases.append(case)
                                print(
                                    json.dumps(
                                        {
                                            k: case[k]
                                            for k in (
                                                "reader",
                                                "hint",
                                                "scenario",
                                                "runs",
                                                "writer_content_events",
                                                "steady_seconds",
                                                "native_terminal_converged",
                                            )
                                        }
                                    )
                                )
        report["execution_status"] = "completed_native_seams"
        if any(not case["conformance_passed"] for case in cases):
            report["execution_status"] = "native_conformance_failed"
    except BaseException as exc:
        report["execution_status"] = "failed"
        report["failure_type"] = type(exc).__name__
        raise
    finally:
        report["harness_sha256_end"] = harness_hashes()
        report["harness_unchanged"] = report["harness_sha256_start"] == report["harness_sha256_end"]
        report["summary"] = summarize(cases)
        report["completed_cases"] = len(cases)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        args.output.with_suffix(".xml").write_bytes(
            tostring(junit_report(cases, report.get("failure_type")), encoding="utf-8")
        )
    if report["execution_status"] == "native_conformance_failed":
        raise SystemExit(1)


def junit_report(cases, failure_type=None):
    failed = failure_type is not None
    suite = Element(
        "testsuite",
        name="native-stream-baseline",
        tests=str(len(cases) + int(failed)),
        failures=str(int(failed) + sum(not c["conformance_passed"] for c in cases)),
    )
    if failed:
        failure = SubElement(
            SubElement(suite, "testcase", name="incomplete_matrix"),
            "failure",
            type=failure_type,
        )
        failure.text = "Native matrix aborted; remaining cells are unverified."
    for case in cases:
        cell = SubElement(
            suite,
            "testcase",
            name="/".join(str(case[k]) for k in ("reader", "hint", "scenario", "runs", "repeat")),
            time=str(case["total_seconds"]),
        )
        if not case["conformance_passed"]:
            SubElement(
                cell, "failure", type="native_delivery_gap"
            ).text = "Terminal/content/tool convergence failed; see measured JSON cell."
    return suite


def cli(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes", type=lambda s: [int(x) for x in s.split(",")], default=[1, 10, 100]
    )
    parser.add_argument(
        "--readers", type=lambda s: s.split(","), default=["session", "task", "agui"]
    )
    parser.add_argument(
        "--hints", type=lambda s: s.split(","), default=["none", "live", "degraded"]
    )
    parser.add_argument(
        "--scenarios", type=lambda s: s.split(","), default=["idle", "stream", "reconnect"]
    )
    parser.add_argument("--pool", choices=["none", "production"], default="production")
    parser.add_argument("--seconds", type=float, default=0.5)
    parser.add_argument("--cadence", type=float, default=0.1)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--output", type=Path, default=Path(".artifacts/stream-baseline.json"))
    args = parser.parse_args(argv)
    if (
        not math.isfinite(args.seconds)
        or not 0 < args.seconds <= 3600
        or not math.isfinite(args.cadence)
        or not 0 < args.cadence <= 3600
        or not 1 <= args.repeats <= 10
        or any(
            not values or len(values) != len(set(values))
            for values in (args.sizes, args.readers, args.hints, args.scenarios)
        )
        or any(x < 1 or x > 100 for x in args.sizes)
        or set(args.readers) - {"session", "task", "agui"}
        or set(args.hints) - {"none", "live", "degraded"}
        or set(args.scenarios) - {"idle", "stream", "short", "tools", "reconnect"}
    ):
        parser.error("invalid bounded workload parameters")
    asyncio.run(main(args))
