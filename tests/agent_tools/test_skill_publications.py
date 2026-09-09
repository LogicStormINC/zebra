"""Publication failures preserve retryable reservations and immutable identity."""

from __future__ import annotations

import asyncio
import io
import threading
from datetime import UTC, datetime, timedelta
from typing import Any
from zipfile import ZipFile

import pytest
from agent_core.domain.artifact_objects import ArtifactObjectReceipt
from agent_core.domain.extensions import ExtensionScope
from agent_core.domain.skill_publications import SkillPublication
from agent_core.ports.skill_publications import SkillPublicationConflictError
from agent_tools.skill_packages import SkillPackageError
from agent_tools.skill_publications import _candidate, publish_skill_package

SCOPE = ExtensionScope(authority_issuer="issuer", namespace_id="tenant",
                       principal_id="user", workspace_id="workspace")


def archive(body: str = "Body", *, comment: bytes = b"", version: str = "v1") -> bytes:
    result = io.BytesIO()
    with ZipFile(result, "w") as bundle:
        bundle.writestr("SKILL.md", "---\nname: sample\ndescription: Sample\n"
                        + (f"version: {version}\n" if version else "") + "---\n" + body)
        bundle.comment = comment
    return result.getvalue()


class Store:
    def __init__(self) -> None:
        self.current: SkillPublication | None = None
        self.fail_ready = False
        self.reserve_count = 0

    async def reserve(self, *, scope: ExtensionScope,
                      publication: SkillPublication) -> SkillPublication:
        self.reserve_count += 1
        if self.current is None:
            self.current = publication
        if not self.current.same_candidate(publication):
            raise SkillPublicationConflictError("conflict")
        return self.current

    async def mark_ready(self, **kwargs: Any) -> SkillPublication:
        if self.fail_ready:
            raise RuntimeError("database unavailable")
        assert self.current is not None
        self.current = SkillPublication.model_validate({
            **self.current.model_dump(), "state": "ready", "receipt": kwargs["receipt"],
        })
        return self.current


class Objects:
    def __init__(self, store: Store | None = None) -> None:
        self.store = store
        self.calls = 0
        self.fail = False
        self.receipt: Any = None
        self.payload: bytes | None = None

    def put_if_absent(self, request: Any) -> ArtifactObjectReceipt:
        if self.store is not None:
            assert self.store.current is not None
        self.calls += 1
        if self.fail:
            raise RuntimeError("object unavailable")
        if self.payload is not None:
            assert self.payload == request.payload
        self.payload = request.payload
        return self.receipt if self.receipt is not None else ArtifactObjectReceipt(
            expectation=request.expectation, object_version="1", verified_at=datetime.now(UTC),
        )


async def publish(data: bytes, store: Any, objects: Any, **kwargs: Any) -> SkillPublication:
    return await publish_skill_package(archive=data, scope=SCOPE, deployment_namespace="test",
                                       store=store, objects=objects, **kwargs)


def test_invalid_zip_performs_no_external_io() -> None:
    store = Store()
    objects = Objects(store)
    with pytest.raises(SkillPackageError):
        asyncio.run(publish(b"invalid", store, objects))
    assert store.reserve_count == objects.calls == 0


@pytest.mark.parametrize("stop", [1, 2, 3])
def test_publication_revalidates_before_each_write(stop: int) -> None:
    store = Store()
    objects = Objects(store)
    calls = 0

    def before_save() -> None:
        nonlocal calls
        calls += 1
        if calls == stop:
            raise PermissionError("revoked")
    with pytest.raises(PermissionError):
        asyncio.run(publish(archive(), store, objects, before_save=before_save))
    assert store.reserve_count == (0 if stop == 1 else 1)
    assert objects.calls == (1 if stop == 3 else 0)
    assert store.current is None or store.current.state == "publishing"


@pytest.mark.parametrize("failure", ["object", "ready"])
def test_failure_retry_and_ready_short_circuit(failure: str) -> None:
    store = Store()
    objects = Objects(store)
    data = archive()
    objects.fail = failure == "object"
    store.fail_ready = failure == "ready"
    with pytest.raises(RuntimeError):
        asyncio.run(publish(data, store, objects))
    assert store.current is not None and store.current.state == "publishing"
    objects.fail = store.fail_ready = False
    ready = asyncio.run(publish(data, store, objects))
    assert ready.state == "ready" and objects.calls == 2
    assert asyncio.run(publish(data, store, objects)) == ready
    assert objects.calls == 2


@pytest.mark.parametrize("data", [archive("Changed"), archive(comment=b"repacked")])
def test_named_version_conflicts_even_on_repack(data: bytes) -> None:
    store = Store()
    objects = Objects(store)
    asyncio.run(publish(archive(), store, objects))
    with pytest.raises(SkillPublicationConflictError):
        asyncio.run(publish(data, store, objects))
    assert objects.calls == 1


@pytest.mark.parametrize("bad", ["untyped", "foreign", "forged"])
def test_bad_receipts_never_mark_ready(bad: str) -> None:
    store = Store()
    objects = Objects(store)
    foreign = _candidate(archive("other"), SCOPE, "test")
    receipt = ArtifactObjectReceipt(expectation=foreign.expectation,
                                    object_version="1", verified_at=datetime.now(UTC))
    objects.receipt = ({"receipt": "bad"} if bad == "untyped" else
                       receipt.model_copy(update={"object_version": ""}) if bad == "forged"
                       else receipt)
    with pytest.raises(ValueError):
        asyncio.run(publish(archive(), store, objects))
    assert store.current is not None and store.current.state == "publishing"


def test_bad_store_response_never_uploads() -> None:
    class Foreign(Store):
        async def reserve(self, **kwargs: Any) -> SkillPublication:
            return _candidate(archive(), SCOPE, "foreign")
    objects = Objects()
    with pytest.raises(ValueError, match="different immutable"):
        asyncio.run(publish(archive(), Foreign(), objects))
    assert objects.calls == 0


def test_cancellation_propagates_after_reservation() -> None:
    class Cancelled(Store):
        async def reserve(self, **kwargs: Any) -> SkillPublication:
            await super().reserve(**kwargs)
            raise asyncio.CancelledError
    store = Cancelled()
    objects = Objects(store)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(publish(archive(), store, objects))
    assert store.current is not None and objects.calls == 0


@pytest.mark.parametrize("bad", ["pending", "foreign", "untyped", "forged", "object_version"])
def test_bad_ready_store_response_fails_closed(bad: str) -> None:
    class Broken(Store):
        async def mark_ready(self, **kwargs: Any) -> Any:
            assert self.current is not None
            if bad == "pending":
                return self.current
            if bad == "untyped":
                return self.current.model_dump()
            ready = await super().mark_ready(**kwargs)
            if bad == "forged":
                return ready.model_copy(update={"receipt": None})
            if bad == "object_version":
                assert ready.receipt is not None
                return ready.model_copy(update={"receipt": ready.receipt.model_copy(
                    update={"object_version": "different"},
                )})
            return _candidate(archive(), SCOPE, "foreign")
    with pytest.raises(ValueError):
        asyncio.run(publish(archive(), Broken(), Objects()))


def test_validation_and_object_io_run_off_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_tools import skill_publications

    main_thread = threading.get_ident()
    original = skill_publications.validate_skill_package
    original_request = skill_publications.ArtifactObjectPutRequest
    worker_threads: list[int] = []

    def validate(data: bytes) -> Any:
        worker_threads.append(threading.get_ident())
        return original(data)

    def request(**kwargs: Any) -> Any:
        worker_threads.append(threading.get_ident())
        return original_request(**kwargs)

    class Threaded(Objects):
        def put_if_absent(self, request: Any) -> ArtifactObjectReceipt:
            worker_threads.append(threading.get_ident())
            return super().put_if_absent(request)
    monkeypatch.setattr(skill_publications, "validate_skill_package", validate)
    monkeypatch.setattr(skill_publications, "ArtifactObjectPutRequest", request)
    asyncio.run(publish(archive(), Store(), Threaded()))
    assert len(worker_threads) == 3 and all(t != main_thread for t in worker_threads)


def test_ready_store_may_preserve_first_verification_time() -> None:
    class Earlier(Store):
        async def mark_ready(self, **kwargs: Any) -> SkillPublication:
            receipt = kwargs["receipt"]
            return await super().mark_ready(**{
                **kwargs, "receipt": receipt.model_copy(update={
                    "verified_at": receipt.verified_at - timedelta(seconds=1),
                }),
            })
    ready = asyncio.run(publish(archive(), Earlier(), Objects()))
    assert ready.receipt is not None and ready.receipt.object_version == "1"
