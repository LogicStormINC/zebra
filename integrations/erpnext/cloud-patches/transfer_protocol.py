"""Fail-closed validation, canonical receipts and protected transfer files."""

import hashlib
import json
import os
import stat
from datetime import UTC
from pathlib import Path

from transfer_inventory import DEFINITIONS, ROUTINES, SEQUENCE_OWNERS, TABLES, TRIGGERS


class Refusal(Exception):
    pass


def require(condition, code):
    if not condition:
        raise Refusal(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def secure_read(path):
    p = Path(path).absolute()
    parent = p.parent.lstat()
    require(
        stat.S_ISDIR(parent.st_mode)
        and stat.S_IMODE(parent.st_mode) == 0o700
        and parent.st_uid == os.geteuid(),
        "protected_directory_mode",
    )
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        require(
            stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600,
            "protected_file_mode",
        )
        require(info.st_uid == os.geteuid(), "protected_file_owner")
        return source.read()


def secure_write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def next_sequence(seq, maximum):
    require(
        seq["start"] == 1
        and seq["increment"] == 1
        and not seq["cycle"]
        and seq["min"] <= 1 <= seq["max"],
        "sequence_parameters",
    )
    if maximum is None:
        return seq["start"], False
    value = max(seq["start"], maximum)
    require(seq["min"] <= value < seq["max"], "sequence_exhausted")
    return value, True


def canonical_migrations():
    # Import immutable installed definitions only; never run a migration/bootstrap.
    from agent_storage.postgres.migrations import MIGRATIONS

    expected = sorted((m.version, m.name, m.checksum) for m in MIGRATIONS)
    require(
        len(expected) == 104
        and expected[-1][:2] == (105, "scoped_plugin_installations")
        and len({r[0] for r in expected}) == 104,
        "pinned_native_catalog_not105",
    )
    return expected


def validate_ledger(rows, expected=None):
    expected = canonical_migrations() if expected is None else expected
    require(
        [tuple(r) for r in rows] == [tuple(r) for r in expected], "source_ledger_not_canonical105"
    )


def classify(table):
    name = table["name"]
    require(name in TABLES, "unknown_relation")
    columns = {c["name"] for c in table["columns"]}
    if name == "zebra_schema_migrations":
        require("deployment_namespace" not in columns, "ledger_scope")
        return "ledger"
    if name in DEFINITIONS:
        require(
            {"namespace_id", "authority_issuer"} <= columns
            and "deployment_namespace" not in columns,
            "definition_scope",
        )
        return "definition"
    require("deployment_namespace" in columns, "unclassified_relation")
    return "deployment"


def validate_catalog(m):
    require([t["name"] for t in m["tables"]] == TABLES, "relation_inventory")
    require(
        len(m["views"]) == 1
        and m["views"][0]["name"] == "task_replay_coverage_privacy"
        and m["views"][0]["definition"],
        "view_inventory",
    )
    require(
        not m["other_relations"] and not m["policies"] and not m["user_types"],
        "unknown_schema_object",
    )
    require(
        [r["name"] for r in m["routines"]] == ROUTINES
        and not any(r["security_definer"] for r in m["routines"]),
        "routine_inventory",
    )
    require([(t["table"], t["name"]) for t in m["triggers"]] == TRIGGERS, "trigger_inventory")
    generated = []
    for table in m["tables"]:
        classify(table)
        require(table["kind"] == "r" and not table["partition"] and table["pk"], "table_shape")
        require(not table["rls"] and not table["force_rls"], "unexpected_rls")
        require(
            len(table["pk"]) == len(set(table["pk"]))
            and set(table["pk"]) <= {c["name"] for c in table["columns"]},
            "primary_key",
        )
        generated.extend(
            (table["name"], c["name"], c["generated"]) for c in table["columns"] if c["generated"]
        )
    require(generated == [("governed_memory_records", "search_vector", "s")], "generated_inventory")
    require(
        len(m["sequences"]) == 4
        and {(s["table"], s["column"]) for s in m["sequences"]} == SEQUENCE_OWNERS,
        "sequence_inventory",
    )
    for sequence in m["sequences"]:
        next_sequence(sequence, None)
    require(m["extensions"] == [{"name": "plpgsql", "version": "1.0"}], "extensions")
    require(
        all(c["validated"] for c in m["constraints"])
        and all(i["valid"] and i["ready"] for i in m["indexes"]),
        "invalid_schema",
    )


def validate_gate(evidence):
    from datetime import datetime as datetime
    from datetime import timezone as timezone

    require(
        evidence.get("version") == 1
        and evidence.get("reviewed_by_operator")
        and evidence.get("site") == "erpnext.zebra.local",
        "operator_gate_identity",
    )
    observed = datetime.fromisoformat(evidence["observed_at"].replace("Z", "+00:00"))
    require(
        0 <= (datetime.now(UTC) - observed).total_seconds() <= 1800,
        "operator_gate_expired",
    )
    require(len(evidence.get("guard_source_commit", "")) == 40, "operator_gate_commit")
    require(
        evidence.get("admission_probe", {}).get("http_status") in (409, 417, 423, 503)
        and evidence["admission_probe"].get("cloud_mutations") == 0
        and evidence["admission_probe"].get("evidence_ref")
        and len(evidence["admission_probe"].get("response_sha256", "")) == 64,
        "operator_gate_probe",
    )
    drain = evidence.get("conversation_lock_drain", {})
    require(
        drain.get("outstanding") == 0
        and isinstance(drain.get("checked"), int)
        and drain["checked"] >= 0
        and drain.get("evidence_ref"),
        "operator_gate_drain",
    )
    require(
        evidence.get("unresolved") == [] and evidence.get("producer_inventory"),
        "operator_gate_unresolved",
    )
    for producer in evidence["producer_inventory"]:
        require(
            set(("identity", "kind", "state", "evidence_ref")) <= set(producer)
            and producer["state"] in ("stopped", "disabled")
            and producer["identity"]
            and producer["evidence_ref"],
            "operator_gate_producer",
        )
    return {
        "sha256": hashlib.sha256(canonical(evidence)).hexdigest(),
        "observed_at": evidence["observed_at"],
        ("assurance"): (
            "operator-reviewed attestation; external Host probe/locks/process"
            " coverage not independently verified by transfer tool"
        ),
    }
