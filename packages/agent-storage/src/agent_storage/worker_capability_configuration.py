"""Pure deployment identity; executable qualification stays in the Worker."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from hashlib import sha256
from typing import Any
from urllib.parse import urlsplit

STRICT_WORKER_CONTRACT = "cov-exec-01:model:bounded-multipart:same-session:validation-mode:v3"
CONTINUATION_PROTOCOL = "coverage-execution-receipt/1"
NATIVE_CONTINUATION_VERIFIER = "native-semantic-commit:execution-receipt/1"


def continuation_configuration_digest(configuration_digest: str) -> str:
    from agent_core.domain.coverage_contracts import coverage_digest

    if type(configuration_digest) is not str or re.fullmatch(
        r"[0-9a-f]{64}", configuration_digest
    ) is None:
        raise ValueError("continuation qualification requires canonical configuration digest")
    return coverage_digest({
        "configuration": configuration_digest, "consumer": CONTINUATION_PROTOCOL,
        "producer": NATIVE_CONTINUATION_VERIFIER,
        "model_proof": "database-maintained-model-revision/87",
        "model_budget": "database-maintained-model-summary/88",
        "task_admission": "database-maintained-task-summary/89",
        "execution_authority": "fresh-read-observation-locked-write-lineage/2",
        "model_volume": "database-maintained-model-volume/91",
        "acceptance": "bounded-exact-unit-batches/1",
        "locked_proof_authority": "pure-operation-entry-exit/1",
        "delta_lookups": "tenant-run-key-indexes/92",
        "membership": "event-sealed-exact-unit-and-record-set/93",
        "artifact_publication": "per-object-authority-atomic-receipt-verified-bytes/4",
        "final_original_reads": "fresh-owner-bounded-pinned-original-bytes/1",
        "checkpoint_publication": "source-owned-run-bound-original-acknowledgement/1",
        "execution_reads": "fresh-authority-full-metadata-readonly-entry-exit/3",
        "materialization_proof": "bounded-native-row-event-pages/94",
        "native_operation": "exact-owner-short-transaction/1",
        "model_settlement": "atomic-original-checkpoint-result/1",
        "model_preparation": "source-qualified-native-semantic-preparation/2",
        "executor_preparation": "source-owned-cpu-entry-guarded-adapters/1",
        "evidence_operation": "bounded-native-producer-usage-unit-settlement/2",
        "recovery_originals": "exact-retained-uploaded-response-without-model-retry/1",
    })


def worker_capability_configuration_digest(
    settings: Any,
    *,
    namespace: str,
    bucket: str,
    key_prefix: str,
    object_endpoint: str | None,
) -> str:
    """Hash only operator settings and the actual composed object namespace."""
    if (
        not isinstance(namespace, str)
        or not namespace.strip()
        or len(namespace) > 512
        or not isinstance(bucket, str)
        or not bucket.strip()
        or len(bucket) > 255
        or not isinstance(key_prefix, str)
        or len(key_prefix) > 1024
        or not isinstance(object_endpoint, str)
        or not object_endpoint.strip()
        or len(object_endpoint) > 4096
        or settings.deployment != "cloud"
        or settings.storage_authority != "postgresql"
    ):
        raise ValueError("strict configuration requires bounded Cloud composition")
    commands = asdict(settings.command_delivery)
    for key in ("relay_url", "consumer_url", "shadow_consumer_url"):
        endpoint = urlsplit(commands[key] or "")
        commands[key] = (endpoint.scheme, endpoint.hostname, endpoint.port, endpoint.path)
    host_endpoint = urlsplit(settings.host_tool_endpoint or "")
    physical_endpoint = urlsplit(object_endpoint)
    if physical_endpoint.scheme not in {"http", "https"} or not physical_endpoint.hostname:
        raise ValueError("strict configuration requires an actual S3 endpoint")
    configuration = {
        "contract": STRICT_WORKER_CONTRACT,
        "deployment": namespace,
        "model": asdict(settings.model),
        "commands": commands,
        "runtime": asdict(settings.runtime),
        "objects": {
            "bucket": bucket,
            "prefix": key_prefix,
            "endpoint": (
                physical_endpoint.scheme,
                physical_endpoint.hostname,
                physical_endpoint.port,
                physical_endpoint.path,
            ),
        },
        "host": {
            "endpoint": (
                host_endpoint.scheme,
                host_endpoint.hostname,
                host_endpoint.port,
                host_endpoint.path,
            ),
            "workload_identity": settings.host_tool_workload_identity,
        },
    }
    body = json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode()
    if len(body) > 64 * 1024:
        raise ValueError("strict deployment descriptor exceeds bound")
    return sha256(body).hexdigest()
