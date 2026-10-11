"""Final proof transport uses remaining deadlines without changing ordinary clients."""

from io import BytesIO
from time import monotonic

import httpx
import pytest
from agent_integrations.host_tools.contracts import HostToolTransportError
from agent_integrations.host_tools.http import HttpHostToolTransport
from agent_storage import S3ArtifactObjectStore

from tests.agent_storage.test_s3_artifact_objects import (
    PAYLOAD,
    _expectation,
    _FakeS3Client,
    _request,
)


def test_host_request_timeout_cannot_override_final_proof_deadline():
    observed = []

    def send(request):
        observed.append(request.extensions["timeout"])
        return httpx.Response(200, json={"ok": True})

    with httpx.Client(transport=httpx.MockTransport(send)) as client:
        transport = HttpHostToolTransport(
            client=client,
            resolver=lambda host: ("8.8.8.8",),
            deadline_monotonic=monotonic() + 1,
        )
        transport.request(
            "GET", "https://example.com/data", headers={}, body=None, timeout_seconds=900
        )
        assert all(0 < value <= 0.25 for value in observed[0].values())
        transport.deadline_monotonic = monotonic() - 1
        with pytest.raises(HostToolTransportError):
            transport.request(
                "GET", "https://example.com/data", headers={}, body=None, timeout_seconds=900
            )
    assert len(observed) == 1


def test_s3_deadline_reader_preserves_exact_original_and_closes_client():
    class Client(_FakeS3Client):
        closed = False

        def get_object(self, **kwargs):
            result = dict(super().get_object(**kwargs))
            result["Body"] = BytesIO(PAYLOAD)
            return result

        def close(self):
            self.closed = True

    client, timeouts = Client(), []

    def factory(timeout):
        timeouts.append(timeout)
        return client

    store = S3ArtifactObjectStore(client, bucket="private", deadline_client_factory=factory)
    expectation = _expectation()
    receipt = store.put_if_absent(_request(expectation))
    assert (
        store.read_version_verified_before(expectation, receipt.object_version, monotonic() + 1)
        == PAYLOAD
    )
    assert client.closed and 0 < timeouts[0] <= 0.25
    with pytest.raises(TimeoutError):
        store.read_version_verified_before(expectation, receipt.object_version, monotonic() - 1)
    assert len(timeouts) == 1


def test_s3_deadline_body_stops_reads_on_exhaustion_and_closes(monkeypatch):
    import agent_storage.artifact_objects as objects

    now = [0.0]

    class SlowBody(BytesIO):
        reads = 0

        def read(self, size):
            self.reads += 1
            now[0] += 2
            return super().read(size)

    body = SlowBody(b"x" * 200000)
    monkeypatch.setattr(objects, "monotonic", lambda: now[0])
    with pytest.raises(TimeoutError):
        objects._read_response_body({"Body": body}, expected_length=200000, deadline=1)
    assert body.closed and body.reads == 1


def test_host_dripping_body_stops_at_absolute_deadline_and_closes(monkeypatch):
    import agent_integrations.host_tools.http as transport_module

    now = [0.0]

    class Drip(httpx.SyncByteStream):
        closed = False
        reads = 0

        def __iter__(self):
            for _ in range(100):
                self.reads += 1
                now[0] += 0.2
                yield b" "

        def close(self):
            self.closed = True

    stream = Drip()
    monkeypatch.setattr(transport_module, "monotonic", lambda: now[0])
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
    ) as client:
        transport = HttpHostToolTransport(
            client=client,
            resolver=lambda host: ("8.8.8.8",),
            deadline_monotonic=1,
        )
        with pytest.raises(HostToolTransportError, match="body deadline"):
            transport.request(
                "GET", "https://example.com/data", headers={}, body=None, timeout_seconds=900
            )
    assert stream.closed and stream.reads == 5
