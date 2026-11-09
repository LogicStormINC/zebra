"""Run: python3 tests/test_resources_checks.py; no ERP, Cloud or model writes."""

import base64
import json
import sys
import types
from pathlib import Path


class Rejected(Exception):
    pass


frappe = types.ModuleType("frappe")
frappe.throw = lambda message, *args: (_ for _ in ()).throw(Rejected(message))
cloud = types.ModuleType("zebra_erpnext.cloud")
sys.modules.update({"frappe": frappe, "zebra_erpnext.cloud": cloud})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
r = __import__("zebra_erpnext", fromlist=("resources",)).resources

FLASH = "deepseek-v4-flash-executor-v1"


def file(name="note.txt", media="text/plain", payload=b"hello"):
    return dict(file_name=name, media_type=media, content_base64=base64.b64encode(payload).decode())


def rejects(fn):
    try:
        fn()
    except Rejected:
        return
    raise AssertionError("Expected rejection")


canonical = r.validate_attachments([file(" note.txt ", " TEXT/PLAIN ")], FLASH)
assert canonical == [file()]
assert r.validate_attachments(None, FLASH) == []
assert r.validate_attachments(json.dumps(canonical), FLASH) == canonical
assert r.attachment_digest(canonical) == r.attachment_digest([file()])
assert r.attachment_digest(canonical) != r.attachment_digest([file(payload=b"other")])
assert r.attachment_digest(canonical) != r.attachment_digest([file(name="other.txt")])
for bad in (
    [file()] * 5,
    [file("../secret")],
    [file("bad\nname")],
    [file(payload=b"")],
    [file(payload=b"\xff")],
    [file(payload=b" " * 3)],
    [file(payload=b"x" * 65537)],
    [file(media="application/octet-stream")],
    [dict(file(), url="https://bad")],
    [dict(file(), content_base64="%%%")],
    [file("note.pdf", "application/pdf", b"not pdf")],
):
    rejects(lambda bad=bad: r.validate_attachments(bad, FLASH))
rejects(lambda: r.validate_attachments([file(payload=b"x" * 65536)] * 3, FLASH))
png = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
)
assert r.validate_attachments([file("pixel.png", "image/png", png)], FLASH)
rejects(
    lambda: r.validate_attachments(
        [file("pixel.png", "image/png", png)], "deepseek-v4-pro-executor-v1"
    )
)
rejects(lambda: r.validate_attachments([file("pixel.gif", "image/gif", png)], FLASH))
large = bytearray(png)
large[16:20] = (8193).to_bytes(4, "big")
rejects(lambda: r.validate_attachments([file("large.png", "image/png", large)], FLASH))


class Doc:
    name = "own"
    task_id = "task-own"


doc = Doc()
owned_calls, requests = [], []


def owned(name):
    owned_calls.append(name)
    if name != "own":
        raise Rejected("Not owned")
    return doc


cloud.owned = owned
artifact = dict(
    artifact_id="artifact-1",
    label="report",
    kind="file",
    preview="safe text",
    uri="https://secret.invalid/credential",
    metadata={"token": "DO NOT RETURN"},
    delivery=dict(file_name="report.txt", mime_type="text/plain", size_bytes=5),
    retrieval=dict(status="payload_available", url="https://secret.invalid"),
    access=dict(allowed=True),
)
replies = []


class Response:
    def __init__(self, value, status=200):
        self.body = json.dumps(value).encode()
        self.status_code = status
        self.closed = False

    def iter_content(self, **kwargs):
        for start in range(0, len(self.body), 13):
            yield self.body[start : start + 13]

    def close(self):
        self.closed = True


def request(doc, method, path, **kwargs):
    assert method == "GET" and kwargs["stream"] and kwargs["raw_response"]
    requests.append(path)
    if path.endswith("/usage"):
        value = dict(
            model_usage=dict(input_tokens=42, model="m", reasoning_content="hidden"),
            attachment_count=1,
        )
    elif path.endswith("/attachments"):
        value = dict(
            attachments=[
                dict(
                    attachment_id="a",
                    file_name="note.txt",
                    media_type="text/plain",
                    size_bytes=5,
                    secret="hidden",
                )
            ],
            has_more=True,
            next_cursor="native-cursor",
        )
    elif path.endswith("/content"):
        value = dict(
            artifact_id="artifact-1",
            status="ok",
            encoding="base64",
            content_base64="aGVsbG8=",
            size_bytes=5,
        )
    elif path.endswith("/artifact-1"):
        value = dict(artifact=artifact)
    elif path.endswith("/artifacts"):
        value = dict(artifacts=[artifact])
    else:
        raise Rejected("Not in owned Task")
    reply = Response(value)
    replies.append(reply)
    return reply


cloud.request = request
rows = r.artifacts("own")
assert (
    rows["history_scope"] == "active_segment"
    and rows["artifacts"][0]["artifact_id"] == "artifact-1"
)
assert "secret" not in json.dumps(rows) and "metadata" not in json.dumps(rows)
artifact["access"]["allowed"] = False
assert "preview" not in r.artifacts("own")["artifacts"][0]
before = len(requests)
rejects(lambda: r.artifact_content("own", "artifact-1"))
assert requests[before:] == ["/tasks/task-own/artifacts/artifact-1"]
artifact["access"]["allowed"] = True
assert r.attachments("own")["attachments"] == [
    dict(attachment_id="a", file_name="note.txt", media_type="text/plain", size_bytes=5)
]
assert r.attachments("own")["next_cursor"] == "native-cursor"
rejects(lambda: r.attachments("own", "x" * 513))
assert r.usage("own")["model_usage"] == {"input_tokens": 42, "model": "m"}
assert r.artifact_detail("own", "artifact-1")["artifact"]["delivery"]["file_name"] == "report.txt"
content = r.artifact_content("own", "artifact-1")
assert content["content_base64"] == "aGVsbG8=" and content["media_type"] == "text/plain"
assert all(reply.closed for reply in replies)
for fn in (
    lambda: r.attachments("other"),
    lambda: r.artifacts("other"),
    lambda: r.usage("other"),
    lambda: r.artifact_detail("other", "artifact-1"),
    lambda: r.artifact_content("other", "artifact-1"),
    lambda: r.artifact_download("other", "artifact-1"),
):
    before = len(requests)
    rejects(fn)
    assert len(requests) == before
for bad in ("../artifact-1", "https://bad", "x?token=y", "x%2fy", "x\\y"):
    before = len(requests)
    rejects(lambda *, bad=bad: r.artifact_detail("own", bad))
    assert len(requests) == before
rejects(lambda: r.artifact_detail("own", "foreign-artifact"))
assert not any("/sessions/" in path for path in requests)
artifact["delivery"]["size_bytes"] = 21 * 1024 * 1024
before = len(requests)
rejects(lambda: r.artifact_content("own", "artifact-1"))
assert len(requests) == before + 1 and not requests[-1].endswith("/content")
artifact["delivery"]["size_bytes"] = 6
rejects(lambda: r.artifact_content("own", "artifact-1"))
reply = Response({"oversized": "x" * 500})
cloud.request = lambda *args, **kwargs: reply
rejects(lambda: r._json(doc, "/artifacts", limit=100))
assert reply.closed
print(
    "PASS native attachment validation/digest, owned finite artifact/"
    "usage projection and constrained downloads"
)
