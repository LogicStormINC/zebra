import json

import httpx
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCallStatus, ToolResult
from zebra_agent_worker.host_media_artifacts import HostMediaArtifactImporter


def _result(url: str = "https://media.example.com/photo.jpg") -> ToolResult:
    return ToolResult(
        tool_call_id=new_tool_call_id(),
        status=ToolCallStatus.EXECUTED,
        output=json.dumps(
            {
                "zebra_artifact_import": {
                    "url": url,
                    "media_kind": "image",
                    "display_name": "evidence",
                    "alt": "Source evidence",
                }
            }
        ),
        metadata={"route": "host_tool_gateway"},
    )


def test_importer_publishes_authorized_media_as_current_session_artifact() -> None:
    published = []
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "image/jpeg", "content-length": "4"},
                content=b"jpeg",
                request=request,
            )
        )
    )
    importer = HostMediaArtifactImporter(
        lambda payload, name, mime: published.append((payload, name, mime))
        or "artifact://00000000-0000-0000-0000-000000000001",
        max_bytes=64,
        resolver=lambda _host: ("93.184.216.34",),
        client=client,
    )

    result = importer.materialize(_result())

    assert result.status is ToolCallStatus.EXECUTED
    assert json.loads(result.output)["artifact_uri"].startswith("artifact://")
    assert result.metadata["artifact_uri"].startswith("artifact://")
    assert result.metadata["media_kind"] == "image"
    assert published == [(b"jpeg", "evidence.jpg", "image/jpeg")]
    client.close()


def test_importer_fails_closed_for_private_host_and_wrong_mime() -> None:
    private = HostMediaArtifactImporter(
        lambda *_args: "artifact://never",
        max_bytes=64,
        resolver=lambda _host: ("127.0.0.1",),
    ).materialize(_result())
    assert private.status is ToolCallStatus.FAILED
    assert private.metadata["reason"] == "private_address_blocked"

    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b"not media",
                request=request,
            )
        )
    )
    wrong_mime = HostMediaArtifactImporter(
        lambda *_args: "artifact://never",
        max_bytes=64,
        resolver=lambda _host: ("93.184.216.34",),
        client=client,
    ).materialize(_result())
    assert wrong_mime.status is ToolCallStatus.FAILED
    assert wrong_mime.metadata["reason"] == "unsupported_content_type"
    client.close()


def test_importer_allows_clash_fake_ip_only_in_trusted_local_mode() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "image/jpeg"},
                content=b"jpeg",
                request=request,
            )
        )
    )
    importer = HostMediaArtifactImporter(
        lambda *_args: "artifact://00000000-0000-0000-0000-000000000001",
        max_bytes=64,
        resolver=lambda _host: ("198.18.4.223",),
        client=client,
        allow_fake_ip_dns=True,
    )

    assert importer.materialize(_result()).status is ToolCallStatus.EXECUTED

    private = HostMediaArtifactImporter(
        lambda *_args: "artifact://never",
        max_bytes=64,
        resolver=lambda _host: ("10.0.0.1",),
        client=client,
        allow_fake_ip_dns=True,
    ).materialize(_result())
    assert private.status is ToolCallStatus.FAILED
    assert private.metadata["reason"] == "private_address_blocked"
    client.close()


def test_importer_ignores_ordinary_host_output() -> None:
    result = ToolResult(
        tool_call_id=new_tool_call_id(),
        status=ToolCallStatus.EXECUTED,
        output='{"items":[]}',
    )
    importer = HostMediaArtifactImporter(
        lambda *_args: "artifact://never",
        max_bytes=64,
    )

    assert importer.materialize(result) is result
