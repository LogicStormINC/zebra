"""Local scratch PostgreSQL/MinIO component load; never a Worker or model accuracy claim."""

import argparse
import gc
import json
import os
import pickle
import tracemalloc
from hashlib import sha256
from tempfile import TemporaryFile
from time import perf_counter
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
from agent_core.domain.artifact_objects import ArtifactObjectExpectation, ArtifactObjectPutRequest
from agent_core.domain.coverage_model_checkpoint import MODEL_CHECKPOINT_KIND
from agent_storage.artifact_objects import S3ArtifactObjectStore
from agent_storage.postgres.coverage_model_checkpoint import _CheckpointBodies
from agent_storage.postgres.coverage_model_replay_rows import original_rows
from agent_storage.postgres.coverage_transactions import iter_run_events, run_events
from botocore.config import Config
from botocore.session import get_session
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def measured(action):
    gc.collect()
    tracemalloc.start()
    started = perf_counter()
    try:
        result = action()
        return result, {
            "seconds": perf_counter() - started,
            "python_peak_bytes": tracemalloc.get_traced_memory()[1],
        }
    finally:
        tracemalloc.stop()


def history_load(dsn: str, count: int) -> dict:
    schema = "coverage_load_" + uuid4().hex
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        connection.execute(f'CREATE SCHEMA "{schema}"')
        connection.execute(f'SET LOCAL search_path TO "{schema}"')
        try:
            connection.execute("""CREATE TABLE session_events (deployment_namespace text,
                session_id uuid,event_id uuid PRIMARY KEY,sequence bigint,event_type text,
                payload jsonb)""")
            connection.execute(
                "CREATE INDEX ON session_events (deployment_namespace,sequence,event_id)"
            )
            session = uuid4()
            with connection.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO session_events VALUES (%s,%s,%s,%s,%s,%s)",
                    (
                        (
                            "load",
                            session,
                            uuid4(),
                            index,
                            "coverage_batch_accepted",
                            Jsonb({"namespace": "load", "run_id": "load", "body": "x" * 1024}),
                        )
                        for index in range(count)
                    ),
                )

            def baseline():
                rows = run_events(connection, "load", "load", "load")
                return digest_rows(iter(rows))

            def paged():
                with TemporaryFile() as spool:
                    total = 0
                    for row in iter_run_events(connection, "load", "load", "load"):
                        pickle.dump(row, spool)
                        total += 1
                    spool.seek(0)

                    def restored():
                        for _ in range(total):
                            yield pickle.load(spool)

                    return digest_rows(restored())

            expected, old = measured(baseline)
            actual, new = measured(paged)
            originals, original_metrics = measured(
                lambda: digest_rows(
                    original_rows(connection, "SELECT * FROM session_events", (), count - 1)
                )
            )
            return {
                "rows": count,
                "page_limit": 100,
                "baseline": old,
                "paged_spool": new,
                "original_metadata_pages": original_metrics,
                "exact_rows_equal": actual == expected,
                "original_metadata_equal": originals == expected,
                "passed": actual == expected
                and originals == expected
                and original_metrics["python_peak_bytes"] < old["python_peak_bytes"]
                and new["python_peak_bytes"] < old["python_peak_bytes"],
            }
        finally:
            # Only this invocation's fresh schema; rollback on error also removes it.
            connection.execute(f'DROP SCHEMA "{schema}" CASCADE')


def digest_rows(rows) -> tuple[int, str]:
    digest, total = sha256(), 0
    for row in rows:
        digest.update(json.dumps(row, sort_keys=True, default=str).encode())
        total += 1
    return total, digest.hexdigest()


def object_load(endpoint: str, count: int) -> dict:
    client = get_session().create_client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["COVERAGE_LOAD_S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["COVERAGE_LOAD_S3_SECRET_KEY"],
        region_name="us-east-1",
        config=Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 1}),
    )
    bucket = "coverage-load-" + uuid4().hex
    client.create_bucket(Bucket=bucket)
    expectations, cleanup = {}, []
    try:
        client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
        store = S3ArtifactObjectStore(client, bucket=bucket)
        for index in range(count):
            body = (f"checkpoint-{index}:" + "x" * 8192).encode()
            identifier = uuid4()
            expectation = ArtifactObjectExpectation(
                deployment_namespace="load",
                artifact_id=identifier,
                sha256=sha256(body).hexdigest(),
                size_bytes=len(body),
            )
            store.put_if_absent(ArtifactObjectPutRequest(expectation=expectation, payload=body))
            expectations[identifier] = expectation

        class Reader:
            reads = 0

            def get_payload(self, identifier):
                expected = expectations[identifier]
                verification = store.verify(expected)
                if verification.receipt is None:
                    raise ValueError("fresh object metadata verification failed")
                return SimpleNamespace(
                    kind=MODEL_CHECKPOINT_KIND,
                    size_bytes=expected.size_bytes,
                    sha256=expected.sha256,
                    version=verification.receipt.object_version,
                )

            def read_payload_bytes_bounded(self, identifier, *, max_bytes):
                self.reads += 1
                if expectations[identifier].size_bytes > max_bytes:
                    raise ValueError("object exceeds read bound")
                return store.read_verified(expectations[identifier])

        def consume(reader):
            digest = sha256()
            for identifier, expected in expectations.items():
                for _ in range(3):
                    body = reader.read_payload_bytes_bounded(
                        identifier, max_bytes=expected.size_bytes
                    )
                    if sha256(body).hexdigest() != expected.sha256:
                        raise ValueError("object bytes changed")
                    digest.update(body)
            return digest.hexdigest()

        reader = Reader()
        expected, old = measured(lambda: consume(reader))
        old_reads, reader.reads = reader.reads, 0
        actual, new = measured(lambda: consume(_CheckpointBodies(reader)))
        return {
            "objects": count,
            "uses_per_object": 3,
            "baseline": old,
            "private_invocation": new,
            "baseline_gets": old_reads,
            "private_gets": reader.reads,
            "exact_bytes_equal": actual == expected,
            "passed": actual == expected and old_reads == count * 3 and reader.reads == count,
        }
    finally:
        # Fresh uniquely named bucket only, including versions if a put failed mid-flight.
        for page in client.get_paginator("list_object_versions").paginate(Bucket=bucket):
            cleanup.extend(
                {"Key": item["Key"], "VersionId": item["VersionId"]}
                for item in page.get("Versions", []) + page.get("DeleteMarkers", [])
            )
        for offset in range(0, len(cleanup), 1000):
            response = client.delete_objects(
                Bucket=bucket, Delete={"Objects": cleanup[offset : offset + 1000], "Quiet": True}
            )
            if response.get("Errors"):
                raise RuntimeError("scratch object cleanup incomplete")
        client.delete_bucket(Bucket=bucket)
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=10003)
    parser.add_argument("--objects", type=int, default=128)
    args = parser.parse_args()
    dsn = os.environ["COVERAGE_LOAD_POSTGRES_DSN"]
    endpoint = os.environ["COVERAGE_LOAD_S3_ENDPOINT"]
    if (
        conninfo_to_dict(dsn).get("host") not in {"127.0.0.1", "localhost"}
        or urlsplit(endpoint).hostname not in {"127.0.0.1", "localhost"}
        or not 101 <= args.rows <= 1000000
        or not 1 <= args.objects <= 1024
    ):
        parser.error("local scratch endpoints and bounded positive load counts are required")
    report = {
        "schema": "zebra.coverage-component-load.v1",
        "synthetic_data": True,
        "postgres": history_load(dsn, args.rows),
        "minio": object_load(endpoint, args.objects),
        "full_worker_acceptance": False,
        "business_semantic_accuracy": "not_evaluated",
    }
    report["passed"] = report["postgres"]["passed"] and report["minio"]["passed"]
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
