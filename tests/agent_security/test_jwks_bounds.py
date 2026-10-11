"""Actual kill/reap, TLS/drip/body and bounded-cache proof for JWKS."""

import ipaddress
import json
import socket
import ssl
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import monotonic

import jwt
import pytest
from agent_security import CachingJwksKeyResolver, HostGrantDecodeError, jwt_adapter
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


@pytest.fixture
def jwks_server(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "ca.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    monkeypatch.setenv("SSL_CERT_FILE", str(cert_path))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = "current"
    body = json.dumps({"keys": [jwk]}).encode()
    stop = threading.Event()
    closed = threading.Event()
    entered = threading.Event()
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            calls.append(self.path)
            self.send_response(200)
            if self.path == "/oversize":
                self.send_header("Content-Length", "65537")
            elif self.path == "/encoded":
                self.send_header("Content-Encoding", "gzip")
            self.end_headers()
            entered.set()
            try:
                if self.path == "/drip":
                    while not stop.wait(0.01):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                elif self.path == "/raw-overflow":
                    self.wfile.write(b" " * 65537)
                elif self.path == "/many-keys":
                    self.wfile.write(json.dumps({"keys": [jwk] * 65}).encode())
                elif self.path == "/mixed-use":
                    self.wfile.write(
                        json.dumps(
                            {"keys": [{**jwk, "use": "enc"}, {**jwk, "use": "sig"}]}
                        ).encode()
                    )
                elif self.path == "/rotating":
                    kid = "current" if calls.count(self.path) == 1 else "rotated"
                    self.wfile.write(json.dumps({"keys": [{**jwk, "kid": kid}]}).encode())
                elif self.path == "/delayed":
                    stop.wait(0.15)
                    self.wfile.write(body)
                else:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
                closed.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert_path, key_path)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://127.0.0.1:{server.server_port}", key, calls, entered, closed
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(1)
        assert not thread.is_alive()


def token(key, kid="current"):
    return jwt.encode({"sub": "not-sent-to-child"}, key, algorithm="RS256", headers={"kid": kid})


def test_native_tls_cache_and_cold_unknown_kid_fetch_once(jwks_server):
    uri, key, calls, _, _ = jwks_server
    resolver = CachingJwksKeyResolver()
    assert resolver.resolve(uri + "/keys", token(key), deadline=monotonic() + 1)
    assert resolver.resolve(uri + "/keys", token(key), deadline=monotonic() + 1)
    assert calls == ["/keys"]
    with pytest.raises(HostGrantDecodeError):
        resolver.resolve(uri + "/unknown", token(key, "unknown"), deadline=monotonic() + 1)
    assert calls == ["/keys", "/unknown"]


def test_native_signing_key_selection_ignores_same_kid_encryption_key(jwks_server):
    uri, key, calls, _, _ = jwks_server
    assert CachingJwksKeyResolver().resolve(
        uri + "/mixed-use", token(key), deadline=monotonic() + 1
    )
    assert calls == ["/mixed-use"]


def test_native_rotation_refreshes_once_and_reuses_new_set(jwks_server):
    uri, key, calls, _, _ = jwks_server
    resolver = CachingJwksKeyResolver()
    for kid in ("current", "rotated", "rotated"):
        assert resolver.resolve(uri + "/rotating", token(key, kid), deadline=monotonic() + 1)
    assert calls == ["/rotating", "/rotating"]


def test_native_concurrent_cold_cache_is_fetched_once(jwks_server):
    uri, key, calls, _, _ = jwks_server
    resolver = CachingJwksKeyResolver()
    signed = token(key)
    barrier = threading.Barrier(5)

    def resolve():
        barrier.wait(timeout=1)
        return resolver.resolve(uri + "/delayed", signed, deadline=monotonic() + 1.5)

    with ThreadPoolExecutor(max_workers=4) as executor:
        pending = [executor.submit(resolve) for _ in range(4)]
        barrier.wait(timeout=1)
        assert all(future.result(timeout=2) for future in pending)
    assert calls == ["/delayed"]


def test_native_cache_waiters_keep_own_deadline_and_recover_after_cold_timeout(jwks_server):
    uri, key, calls, entered, closed = jwks_server
    resolver = CachingJwksKeyResolver()
    signed = token(key)
    assert resolver.resolve(uri + "/keys", signed, deadline=monotonic() + 1)
    entered.clear()
    barrier = threading.Barrier(5)

    def waiting():
        barrier.wait(timeout=1)
        started = monotonic()
        with pytest.raises(TimeoutError, match="cache admission"):
            resolver.resolve(uri + "/keys", signed, deadline=started + 0.06)
        assert monotonic() - started < 0.3

    with ThreadPoolExecutor(max_workers=5) as executor:
        cold = executor.submit(resolver.resolve, uri + "/drip", signed, deadline=monotonic() + 0.6)
        assert entered.wait(0.4)
        pending = [executor.submit(waiting) for _ in range(4)]
        barrier.wait(timeout=1)
        for future in pending:
            future.result(timeout=0.5)
        with pytest.raises(TimeoutError):
            cold.result(timeout=1)
    assert closed.wait(0.5)
    assert resolver.resolve(uri + "/keys", signed, deadline=monotonic() + 0.5)
    assert calls == ["/keys", "/drip"]


@pytest.mark.parametrize("path", ["/oversize", "/raw-overflow", "/encoded", "/many-keys"])
def test_native_raw_body_and_encoding_are_bounded(jwks_server, path):
    uri, key, _, entered, _ = jwks_server
    with pytest.raises(HostGrantDecodeError):
        CachingJwksKeyResolver().resolve(uri + path, token(key), deadline=monotonic() + 1)
    assert entered.is_set()


def test_native_drip_deadline_closes_actual_peer_and_reaps_child(jwks_server, monkeypatch):
    uri, key, _, entered, closed = jwks_server
    children = []
    spawn = subprocess.Popen

    def record(*args, **kwargs):
        child = spawn(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", record)
    started = monotonic()
    with pytest.raises(TimeoutError):
        CachingJwksKeyResolver().resolve(uri + "/drip", token(key), deadline=started + 0.4)
    assert monotonic() - started < 0.9
    assert entered.is_set() and closed.wait(0.5)
    assert len(children) == 1 and children[0].poll() is not None
    assert "not-sent-to-child" not in str(children[0].args)


def test_stalled_dns_child_is_killed_reaped_and_no_token_passed(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "stalled.invalid")
    monkeypatch.setattr(
        jwt_adapter,
        "_FETCH_SCRIPT",
        "import socket,time\nsocket.getaddrinfo=lambda *a,**k:time.sleep(10)\n"
        + jwt_adapter._FETCH_SCRIPT,
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    children = []
    spawn = subprocess.Popen

    def record(*args, **kwargs):
        child = spawn(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", record)
    started = monotonic()
    with pytest.raises(TimeoutError):
        CachingJwksKeyResolver().resolve(
            "https://stalled.invalid/keys", token(key), deadline=started + 0.2
        )
    assert monotonic() - started < 0.7
    assert children[0].poll() is not None


def test_cache_and_key_count_bounds(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = "current"
    resolver = CachingJwksKeyResolver()
    monkeypatch.setattr(resolver, "_fetch", lambda *args: jwt.PyJWKSet.from_dict({"keys": [jwk]}))
    for index in range(40):
        resolver.resolve(f"https://keys-{index}.example/keys", token(key))
    assert len(resolver._sets) == 32


def test_cache_lock_wait_uses_request_deadline():
    resolver = CachingJwksKeyResolver()
    resolver._lock.acquire()
    try:
        started = monotonic()
        with pytest.raises(TimeoutError):
            resolver.resolve("https://keys.example/keys", "ignored", deadline=started + 0.05)
        assert monotonic() - started < 0.25
    finally:
        resolver._lock.release()


def test_native_stalled_tls_handshake_is_terminated_and_reaped(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    entered, closed = threading.Event(), threading.Event()
    children = []
    spawn = subprocess.Popen

    def record(*args, **kwargs):
        child = spawn(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", record)
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        server.settimeout(1)

        def peer():
            with server.accept()[0] as accepted:
                entered.set()
                accepted.settimeout(1)
                while accepted.recv(65536):
                    pass
            closed.set()

        thread = threading.Thread(target=peer, daemon=True)
        thread.start()
        started = monotonic()
        with pytest.raises(TimeoutError):
            CachingJwksKeyResolver().resolve(
                f"https://127.0.0.1:{server.getsockname()[1]}/keys",
                token(key),
                deadline=started + 0.3,
            )
        assert monotonic() - started < 0.7
        assert entered.is_set() and closed.wait(0.5)
        thread.join(0.5)
        assert not thread.is_alive()
    assert len(children) == 1 and children[0].poll() is not None
