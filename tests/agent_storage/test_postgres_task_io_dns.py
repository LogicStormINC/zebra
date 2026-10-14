"""Direct DNS uses a killable stdlib child; libpq still owns complex settings."""

import json
import os
import subprocess
import sys

import pytest
from agent_storage.postgres.task_io import RESOLVE_SCRIPT


def test_explicit_single_host_resolver_does_not_import_psycopg():
    # -S removes site-packages: this fails if the simple path imports psycopg.
    params = {
        "host": "localhost", "port": "5432", "user": "reader",
        "password": "not-a-secret", "sslmode": "verify-full",
    }
    environment = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    result = subprocess.run(
        [sys.executable, "-S", "-c", RESOLVE_SCRIPT],
        input=json.dumps(params), text=True, capture_output=True, env=environment, timeout=2,
    )
    assert result.returncode == 0, result.stderr
    attempts = json.loads(result.stdout)
    assert attempts and all(attempt["hostaddr"] in {"127.0.0.1", "::1"} for attempt in attempts)
    assert all(
        {k: v for k, v in attempt.items() if k != "hostaddr"} == params for attempt in attempts
    )


@pytest.mark.parametrize("params,pg_environment", [
    ({"host": "one.example", "port": "5432"}, {}),
    ({"host": "one.example"}, {}),
    ({"host": "one.example,two.example", "port": "5432,5433"}, {}),
    ({"host": "one.example", "port": "5432", "target_session_attrs": "prefer-standby"}, {}),
    ({"host": "one.example", "port": "5432"}, {"PGTARGETSESSIONATTRS": "prefer-standby"}),
    ({"host": "one.example", "port": "5432", "load_balance_hosts": "random"}, {}),
    ({"host": "one.example", "port": "5432"}, {"PGLOADBALANCEHOSTS": "random"}),
    ({"port": "5432"}, {"PGHOST": "one.example"}),
])
def test_resolver_matches_psycopg_attempts_for_direct_and_complex_settings(params, pg_environment):
    environment = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    environment.update(pg_environment)
    # Controlled DNS in both children; test ordering without network variability.
    prefix = """import socket
socket.getaddrinfo=lambda host,port,**kw: [
    (socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',('127.0.0.1',int(port))),
    (socket.AF_INET6,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',('::1',int(port),0,0))]
"""
    reference = """import json,sys
from psycopg._conninfo_attempts import conninfo_attempts
json.dump(conninfo_attempts(json.load(sys.stdin)),sys.stdout)
"""
    outputs = []
    for script in (RESOLVE_SCRIPT, reference):
        result = subprocess.run(
            [sys.executable, "-c", prefix + script], input=json.dumps(params),
            text=True, capture_output=True, env=environment, timeout=2,
        )
        assert result.returncode == 0, result.stderr
        attempts = json.loads(result.stdout)
        if params.get("load_balance_hosts", pg_environment.get("PGLOADBALANCEHOSTS")) == "random":
            attempts.sort(key=lambda item: item["hostaddr"])
        outputs.append(attempts)
    assert outputs[0] == outputs[1]
