"""One idle Native scheduler cycle in the QA namespace; never create due work."""

import json
import subprocess

from prepare_full_capability_qa import NETWORK, PREFIX, ROOT


def main():
    record = json.loads((ROOT / "inventory.json").read_text())
    if record["prefix"] != PREFIX or record["worker_started"] is not False:
        raise ValueError("idle QA only")
    site = json.loads((ROOT / "site.json").read_text())["zebra_agent"]
    candidate = site["runtimes"]["cloud114"]
    env = (ROOT / "api.env").read_text()
    values = dict(
        ZEBRA_SCHEDULER_ID="erp-full-qa-idle",
        ZEBRA_SCHEDULER_GRANT_EXCHANGE_PROTOCOL="generic",
        ZEBRA_SCHEDULER_GRANT_ISSUER=site["issuer"],
        ZEBRA_SCHEDULER_GRANT_AUDIENCE="zebra",
        ZEBRA_SCHEDULER_GRANT_JWKS_URI=site["issuer"] + "/api/method/zebra_erpnext.gateway.jwks",
        ZEBRA_SCHEDULER_ALLOWED_ORIGINS=site["origin"],
        ZEBRA_SCHEDULER_GRANT_EXCHANGE_URL=site["issuer"]
        + "/api/method/zebra_erpnext.api.schedule_exchange",
        ZEBRA_SCHEDULER_WORKLOAD_IDENTITY="erpnext-scheduler-full",
        ZEBRA_SCHEDULER_WORKLOAD_SHARED_SECRET=candidate["schedule_workload_secret"],
    )
    path = ROOT / "scheduler.env"
    path.write_text(env + "".join(k + "=" + v + "\n" for k, v in values.items()))
    path.chmod(0o600)
    # A real DB assertion before starting even an idle cycle: every owned schedule
    # is either paused or in 2099; do not consume a copied due schedule.
    sql = (
        "SELECT count(*) FROM task_schedules WHERE deployment_namespace='"
        "erpnext-full' AND status='active' AND next_fire_at < '2099-01-01"
        "'::timestamptz;"
    )
    count = subprocess.check_output(
        [
            "docker",
            "exec",
            PREFIX + "-pg",
            "psql",
            "-U",
            "erpnext_agent",
            "-d",
            "erp_agent_capability_qa_20261028",
            "-Atc",
            sql,
        ],
        text=True,
    ).strip()
    if count != "0":
        raise ValueError("due QA schedule exists; no materializer started")
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            NETWORK,
            "--env-file",
            str(path),
            "-v",
            str(ROOT / "tls") + ":/qa:ro",
            "-v",
            str(ROOT / "mcp") + ":/mcp:ro",
            "--entrypoint",
            "python",
            record["native_image"],
            "-m",
            "zebra_agent_scheduler.main",
            "--once",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:])
    (ROOT / "scheduler-idle-gate.json").write_text(
        json.dumps(
            dict(
                stage="real_native_scheduler_idle_cycle",
                result=result.stdout.strip(),
                due_schedules=0,
                model_calls=0,
                search_calls=0,
            ),
            indent=2,
        )
    )
    print(result.stdout.strip())


if __name__ == "__main__":
    main()
