import hashlib
import json
import os
import stat
import subprocess
import uuid
from pathlib import Path

from transfer_inventory import (
    API_IMAGE,
    CONSUMERS,
    PG_IMAGE,
    SOURCE_CONTAINER,
    SOURCE_DATABASE,
    SOURCE_NETWORK,
    SOURCE_ROLE,
    TABLES,
)
from transfer_protocol import Refusal, canonical, require, secure_read, secure_write, validate_gate
from transfer_worker_bundle import worker_bundle


class Host:
    def __init__(self, path, disposable_qa=False):
        self.disposable_qa = disposable_qa
        os.umask(0o077)
        self.cfg = json.loads(secure_read(path))
        cfg = self.cfg
        keys = {
            "source",
            "destination",
            "destination_container",
            "destination_network",
            "destination_volume",
            "evidence_directory",
        }
        keys |= (
            {"qa_source_container", "qa_source_network"}
            if disposable_qa
            else {"gate_evidence", "gate_sha256"}
        )
        require(set(cfg) == keys, "configuration_keys")
        for name in ("source", "destination"):
            require(
                set(cfg[name]) <= {"host", "port", "dbname", "user", "password", "sslmode"}
                and {"host", "dbname", "user", "password"} <= set(cfg[name]),
                "connection_keys",
            )
            require(all(isinstance(v, str | int) for v in cfg[name].values()), "connection_values")
            require(cfg[name].get("port", 5432) == 5432, "connection_port")
            require(
                all(
                    isinstance(cfg[name][k], str) and cfg[name][k] and "\x00" not in cfg[name][k]
                    for k in ("host", "dbname", "user", "password")
                ),
                "connection_values",
            )
        self.source_container = cfg.get("qa_source_container", SOURCE_CONTAINER)
        self.source_network = cfg.get("qa_source_network", SOURCE_NETWORK)
        self.source_database, self.source_role = cfg["source"]["dbname"], cfg["source"]["user"]
        if disposable_qa:
            require(
                self.source_container.startswith("erpnext-db-qa-source-")
                and cfg["destination_container"].startswith("erpnext-db-qa-target-")
                and self.source_network == cfg["destination_network"]
                and self.source_network.startswith("erpnext-db-transfer-qa-")
                and self.source_database.startswith("zebra_transfer_qa_source_")
                and cfg["destination"]["dbname"].startswith("erpnext_agent_qa_"),
                "disposable_qa_identity",
            )
        else:
            require(
                self.source_database == SOURCE_DATABASE and self.source_role == SOURCE_ROLE,
                "source_configuration",
            )
            require(cfg["destination_network"] != SOURCE_NETWORK, "distinct_configuration")
        require(cfg["destination_container"] != self.source_container, "distinct_configuration")
        self.directory = Path(cfg["evidence_directory"]).absolute()
        require(
            self.directory.is_dir()
            and not self.directory.is_symlink()
            and stat.S_IMODE(self.directory.stat().st_mode) == 0o700
            and self.directory.stat().st_uid == os.geteuid(),
            "evidence_directory",
        )
        # Every invocation gets an immutable subdirectory; never reuse an incomplete target.
        self.run_directory = self.directory / ("transfer-" + uuid.uuid4().hex)
        self.run_directory.mkdir(mode=0o700)
        self.log = open(self.run_directory / "diagnostics.log", "xb")
        os.chmod(self.log.name, 0o600)
        self.process = None
        self.container = None
        self.phase = "host_preflight"

    def run(self, args, stdout=subprocess.PIPE, stdin=None):
        try:
            result = subprocess.run(args, stdin=stdin, stdout=stdout, stderr=self.log, check=True)
            return result.stdout
        except subprocess.CalledProcessError:
            raise Refusal("native_command_failed") from None

    def inspect_container(self, name):
        return json.loads(self.run(["docker", "inspect", name]))[0]

    def gates(self):
        if self.disposable_qa:
            network = json.loads(self.run(["docker", "network", "inspect", self.source_network]))[0]
            allowed = {self.source["Id"], self.target["Id"]} | (
                {self.container} if self.container else set()
            )
            require(
                network["Internal"] and set(network.get("Containers", {})) <= allowed,
                "qa_network_consumer",
            )
            return {
                ("assurance"): (
                    "disposable QA only; isolated internal network contains only two "
                    "verified database servers and maintenance process"
                )
            }
        for name in CONSUMERS:
            state = self.inspect_container(name)["State"]
            require(
                state["Status"] in ("exited", "created")
                and not state["Running"]
                and not state.get("Restarting"),
                "source_consumer_running",
            )
        raw = secure_read(self.cfg["gate_evidence"])
        require(
            hashlib.sha256(raw).hexdigest() == self.cfg["gate_sha256"], "operator_gate_fingerprint"
        )
        gate = validate_gate(json.loads(raw))
        network = json.loads(
            self.run(["docker", "network", "inspect", self.cfg["destination_network"]])
        )[0]
        allowed = {self.target["Id"]}
        if self.container:
            allowed.add(self.container)
        require(set(network.get("Containers", {})) <= allowed, "destination_network_consumer")
        gate["raw_file_sha256"] = self.cfg["gate_sha256"]
        return gate

    def preflight(self, transfer=False):
        cfg = self.cfg
        self.source = self.inspect_container(self.source_container)
        self.target = self.inspect_container(cfg["destination_container"])
        require(self.source["Id"] != self.target["Id"], "same_container")
        for container in (self.source, self.target):
            require(
                container["Image"] == PG_IMAGE and container["State"]["Running"],
                "postgres_image_or_state",
            )
        require(
            set(self.source["NetworkSettings"]["Networks"]) == {self.source_network},
            "source_network_drift",
        )
        require(
            set(self.target["NetworkSettings"]["Networks"]) == {cfg["destination_network"]},
            "target_network",
        )
        require(
            not self.target["HostConfig"].get("PortBindings")
            and not any(self.target["NetworkSettings"]["Ports"].values()),
            "published_destination_port",
        )
        require(self.target["HostConfig"].get("NetworkMode") != "host", "target_host_network")
        if self.disposable_qa:
            require(
                all(
                    c["Config"].get("Labels", {}).get("zebra.erp.qa") == "database-transfer"
                    for c in (self.source, self.target)
                ),
                "qa_container_label",
            )
        source_mounts = {m["Source"] for m in self.source["Mounts"]}
        mounts = [
            m for m in self.target["Mounts"] if m["Destination"] == "/var/lib/postgresql/data"
        ]
        require(
            len(mounts) == 1
            and mounts[0]["Type"] == "volume"
            and mounts[0]["Name"] == cfg["destination_volume"]
            and mounts[0]["Source"] not in source_mounts,
            "distinct_target_volume",
        )
        self.source_address = self.source["NetworkSettings"]["Networks"][self.source_network][
            "IPAddress"
        ]
        self.target_address = self.target["NetworkSettings"]["Networks"][
            cfg["destination_network"]
        ]["IPAddress"]
        require(
            cfg["source"]["host"] == self.source_address
            and cfg["destination"]["host"] == self.target_address
            and self.source_address != self.target_address,
            "connection_container_address",
        )
        require(
            self.run(["docker", "image", "inspect", "--format", "{{.Id}}", API_IMAGE])
            .decode()
            .strip()
            == API_IMAGE,
            "worker_image",
        )
        self.host_identity = {
            "docker_engine": self.run(["docker", "info", "--format", "{{.ID}}"]).decode().strip(),
            "source_container": self.source["Id"],
            "destination_container": self.target["Id"],
            "source_image": self.source["Image"],
            "destination_image": self.target["Image"],
            "source_mounts": self.source["Mounts"],
            "destination_mounts": self.target["Mounts"],
            "source_network": json.loads(
                self.run(["docker", "network", "inspect", self.source_network])
            )[0]["Id"],
            "destination_network": json.loads(
                self.run(["docker", "network", "inspect", cfg["destination_network"]])
            )[0]["Id"],
        }
        require(self.host_identity["docker_engine"], "docker_engine_identity")
        if transfer:
            return self.gates()
        return None

    def start_worker(self):
        config = {
            "source": self.cfg["source"],
            "destination": self.cfg["destination"],
            "source_address": self.source_address,
            "target_address": self.target_address,
            "disposable_qa": self.disposable_qa,
        }
        secure_write(self.run_directory / "worker.json", canonical(config))
        secure_write(self.run_directory / "worker.py", worker_bundle())
        self.container = (
            self.run(
                [
                    "docker",
                    "create",
                    "--interactive",
                    "--network",
                    self.source_network,
                    "--user",
                    f"{os.geteuid()}:{os.getegid()}",
                    "--read-only",
                    "--cap-drop=ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--mount",
                    f"type=bind,src={self.run_directory},dst=/transfer,readonly",
                    "--entrypoint",
                    "/app/.venv/bin/python",
                    API_IMAGE,
                    "/transfer/worker.py",
                    "worker",
                    "/transfer/worker.json",
                ]
            )
            .decode()
            .strip()
        )
        require(
            len(self.container) == 64 and all(c in "0123456789abcdef" for c in self.container),
            "maintenance_container_id",
        )
        if self.cfg["destination_network"] != self.source_network:
            self.run(
                ["docker", "network", "connect", self.cfg["destination_network"], self.container]
            )
        self.process = subprocess.Popen(
            ["docker", "start", "--attach", "--interactive", self.container],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log,
            text=True,
            bufsize=1,
        )

    def command(self, command, **arguments):
        self.phase = command
        self.process.stdin.write(json.dumps({"command": command, "arguments": arguments}) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline(32_000_000)
        require(line and line.endswith("\n"), "worker_protocol_lost")
        response = json.loads(line)
        if not response.get("ok"):
            # Only the fixed-code worker response may reach the user, never native stderr.
            raise Refusal(
                "worker_"
                + response.get("reason", "failure")
                + "_sqlstate_"
                + str(response.get("sqlstate"))
            )
        return response["result"]

    def dump(self, section, snapshot):
        require(
            isinstance(snapshot, str)
            and len(snapshot) < 100
            and all(c in "0123456789ABCDEFabcdef-" for c in snapshot),
            "snapshot_identifier",
        )
        path = self.run_directory / (section + ".sql")
        with open(path, "xb") as out:
            self.run(
                [
                    "docker",
                    "exec",
                    "-u",
                    "postgres",
                    self.source["Id"],
                    "pg_dump",
                    "-U",
                    self.source_role,
                    "-d",
                    self.source_database,
                    "--schema-only",
                    "--schema=public",
                    "--no-owner",
                    "--no-acl",
                    "--section=" + section,
                    "--snapshot=" + snapshot,
                    "--lock-wait-timeout=10s",
                ],
                stdout=out,
            )
        os.chmod(path, 0o600)
        return path

    def restore(self, path, pre=False):
        destination = self.cfg["destination"]
        # Local Unix socket authentication must already be operator-configured. No
        # password in argv/env.
        if pre:
            restore = self.run_directory / "pre-restore.sql"
            with open(restore, "xb") as out, open(path, "rb") as source:
                out.write(b"DROP SCHEMA public RESTRICT;\n")
                while block := source.read(1024 * 1024):
                    out.write(block)
            os.chmod(restore, 0o600)
        else:
            restore = path
        with (
            open(restore, "rb") as source,
            open(self.run_directory / ("pre-psql.log" if pre else "post-psql.log"), "xb") as output,
        ):
            self.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    "-u",
                    "postgres",
                    self.target["Id"],
                    "psql",
                    "-X",
                    "-w",
                    "-U",
                    destination["user"],
                    "-d",
                    destination["dbname"],
                    "-v",
                    "ON_ERROR_STOP=1",
                    "--single-transaction",
                ],
                stdin=source,
                stdout=output,
            )

    def execute(self, mode, approved_path=None, fingerprint=None):
        failed = False
        try:
            gate = self.preflight(mode == "transfer")
            if mode == "transfer":
                raw = secure_read(approved_path)
                approved = json.loads(raw)
                require(hashlib.sha256(raw).hexdigest() == fingerprint, "approved_file_fingerprint")
                require(
                    approved.get("host_identity") == self.host_identity,
                    "approved_host_identity_drift",
                )
            self.start_worker()
            snapshot = self.command("open_snapshot")
            snapshot["host_identity"] = self.host_identity
            secure_write(self.run_directory / "inspection.json", canonical(snapshot))
            if mode == "inspect":
                self.command("abort")
                return {
                    "status": "inspection_only",
                    "fingerprint": hashlib.sha256(canonical(snapshot)).hexdigest(),
                    "inspection_file": str(self.run_directory / "inspection.json"),
                    "tables": len(TABLES),
                    "destination_mutations": False,
                    "gate_required_before_transfer": True,
                }
            self.command("target", approved=approved)
            self.phase = "dump_schema"
            pre = self.dump("pre-data", snapshot["snapshot"])
            post = self.dump("post-data", snapshot["snapshot"])
            self.gates()
            self.phase = "restore_pre_data"
            self.restore(pre, True)
            self.command("pre_restored")
            self.command("copy_rows")
            self.phase = "restore_post_data"
            self.restore(post)
            report = self.command("verify")
            self.gates()
            report["operator_gate"] = gate
            report["host_identity"] = self.host_identity
            secure_write(self.run_directory / "verified.json", canonical(report))
            self.command("abort")
            return {
                "status": report["status"],
                "report_file": str(self.run_directory / "verified.json"),
                "fingerprint": report["fingerprint"],
                "consumers_released": False,
            }
        except BaseException:
            failed = True
            self.record_incomplete()
            raise
        finally:
            try:
                self.close()
            except BaseException:
                self.record_incomplete()
                if not failed:
                    raise

    def record_incomplete(self):
        try:
            secure_write(
                self.run_directory / "INCOMPLETE.json",
                canonical(
                    {
                        "phase": self.phase,
                        "status": "incomplete_unactivated",
                        ("warning"): (
                            "pre-data, data, post-data and sequence changes may already be du"
                            "rable; do not retry into this target or release consumers"
                        ),
                    }
                ),
            )
        except OSError:
            pass  # Preserve the primary failure even if evidence storage itself fails.

    def close(self):
        self.cleanup_report = {
            "maintenance_container_absent": self.container is None,
            "credential_copy_removed": False,
            "errors": [],
        }
        try:
            if self.process and self.process.poll() is None:
                try:
                    self.process.stdin.close()
                    self.process.wait(timeout=10)
                except (OSError, subprocess.TimeoutExpired):
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait()
        except BaseException:
            self.cleanup_report["errors"].append("attach_process_termination_failed")
        try:
            if self.container:
                self.run(["docker", "rm", "--force", self.container])
                self.cleanup_report["maintenance_container_absent"] = True
        except BaseException:
            self.cleanup_report["errors"].append("maintenance_container_removal_not_proven")
        finally:
            try:
                (self.run_directory / "worker.json").unlink(missing_ok=True)
                self.cleanup_report["credential_copy_removed"] = True
            except OSError:
                self.cleanup_report["errors"].append("credential_copy_removal_failed")
            self.log.close()
        if self.cleanup_report["errors"]:
            try:
                secure_write(
                    self.run_directory / "CLEANUP_INCOMPLETE.json", canonical(self.cleanup_report)
                )
            except OSError:
                pass
            raise Refusal("maintenance_cleanup_incomplete")
