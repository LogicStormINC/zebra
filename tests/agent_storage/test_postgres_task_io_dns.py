"""Direct DNS uses a killable stdlib child; libpq still owns complex settings."""

import json
import os
import subprocess
import sys

import pytest
from agent_storage.postgres.task_io import RESOLVE_SCRIPT


def test_explicit_single_host_resolver_needs_no_json_or_driver_in_child(monkeypatch):
    import socket
    from time import monotonic

    from agent_storage.postgres import task_io

    for key in os.environ:
        if key.startswith("PG"):
            monkeypatch.delenv(key)
    factory = task_io.TaskIoConnections(
        "host=localhost port=5432 user=reader password='private test value' sslmode=verify-full"
    )
    original = subprocess.Popen
    commands = []
    blocked_imports = """import builtins
original_import=builtins.__import__
def required_stdlib_only(name,*args,**kwargs):
    if name == 'encodings.idna' or name.split('.')[0] in {'json','psycopg'}:
        raise RuntimeError('direct DNS child imported unnecessary serialization/driver')
    return original_import(name,*args,**kwargs)
builtins.__import__=required_stdlib_only
"""

    def spawn(command, **kwargs):
        commands.append(command)
        assert "private test value" not in repr(command)
        command = list(command)
        index = command.index("-c") + 1
        command[index] = blocked_imports + command[index]
        return original(command, **kwargs)

    monkeypatch.setattr(task_io.subprocess, "Popen", spawn)
    attempts = factory._resolve(monotonic() + 2)
    expected = socket.getaddrinfo(
        "localhost", "5432", proto=socket.IPPROTO_TCP, type=socket.SOCK_STREAM
    )
    assert [item["hostaddr"] for item in attempts] == [item[4][0] for item in expected]
    assert all(
        {k: v for k, v in item.items() if k != "hostaddr"} == factory._params for item in attempts
    )
    assert len(commands) == 1 and "-S" in commands[0]


@pytest.mark.parametrize(
    "params,pg_environment",
    [
        ({"host": "one.example", "port": "5432"}, {}),
        ({"host": "数据库.example", "port": "5432"}, {}),
        ({"host": "one.example"}, {}),
        ({"host": "one.example,two.example", "port": "5432,5433"}, {}),
        ({"host": "one.example", "port": "5432", "target_session_attrs": "prefer-standby"}, {}),
        ({"host": "one.example", "port": "5432"}, {"PGTARGETSESSIONATTRS": "prefer-standby"}),
        ({"host": "one.example", "port": "5432", "load_balance_hosts": "random"}, {}),
        ({"host": "one.example", "port": "5432"}, {"PGLOADBALANCEHOSTS": "random"}),
        ({"port": "5432"}, {"PGHOST": "one.example"}),
    ],
)
def test_resolver_matches_psycopg_attempts_for_direct_and_complex_settings(
    params, pg_environment, monkeypatch
):
    environment = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    environment.update(pg_environment)
    # Controlled DNS in both children; test ordering without network variability.
    prefix = """import socket,_socket
socket.getaddrinfo=_socket.getaddrinfo=lambda host,port,**kw: [
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
            [sys.executable, "-c", prefix + script],
            input=json.dumps(params),
            text=True,
            capture_output=True,
            env=environment,
            timeout=2,
        )
        assert result.returncode == 0, result.stderr
        attempts = json.loads(result.stdout)
        if params.get("load_balance_hosts", pg_environment.get("PGLOADBALANCEHOSTS")) == "random":
            attempts.sort(key=lambda item: item["hostaddr"])
        outputs.append(attempts)
    assert outputs[0] == outputs[1]

    from time import monotonic

    from agent_storage.postgres import task_io
    from psycopg.conninfo import make_conninfo

    for key in os.environ:
        if key.startswith("PG"):
            monkeypatch.delenv(key)
    for key, value in pg_environment.items():
        monkeypatch.setenv(key, value)
    spawn = subprocess.Popen

    def controlled(command, **kwargs):
        command = list(command)
        index = command.index("-c") + 1
        command[index] = prefix + command[index]
        return spawn(command, **kwargs)

    monkeypatch.setattr(task_io.subprocess, "Popen", controlled)
    actual = list(task_io.TaskIoConnections(make_conninfo("", **params))._resolve(monotonic() + 2))
    if params.get("load_balance_hosts", pg_environment.get("PGLOADBALANCEHOSTS")) == "random":
        actual.sort(key=lambda item: item["hostaddr"])
    assert actual == outputs[1]


def test_stalled_direct_child_is_killed_and_reaped(monkeypatch):
    from time import monotonic

    from agent_storage.postgres import task_io

    children, spawn = [], subprocess.Popen

    def record(*args, **kwargs):
        child = spawn(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(task_io, "RESOLVE_HOST_SCRIPT", "import time; time.sleep(10)")
    monkeypatch.setattr(task_io.subprocess, "Popen", record)
    factory = task_io.TaskIoConnections("host=localhost port=5432 password=private-test")
    started = monotonic()
    with pytest.raises(TimeoutError, match="DNS deadline"):
        factory._resolve(started + 0.25)
    assert monotonic() - started < 0.7
    assert len(children) == 1 and children[0].poll() is not None
    assert "private-test" not in repr(children[0].args)
