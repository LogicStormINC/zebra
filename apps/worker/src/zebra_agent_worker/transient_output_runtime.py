"""Optional ordinary-public callback transport; default composition is dormant."""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from threading import RLock
from time import monotonic
from uuid import uuid4

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.leases import LeaseFence, WorkerLease
from agent_core.domain.stream_admission import RunStreamAdmission, StreamMode
from agent_core.domain.transient_output import MAX_TRANSIENT_FRAME_BYTES, TransientTextFrame
from agent_core.harness.models import HarnessEventDraft
from agent_core.harness.public_output_lifecycle import public_output_lock
from agent_core.ports.agent_tasks import AgentTaskPort
from agent_core.ports.lease_store import LeaseStorePort
from agent_core.ports.transient_output import (
    TransientOutputPort,
    TransientStreamScope,
    TransientWriterAuthorization,
)
from agent_integrations.redis_transient_output import TransientOutputUnavailable
from agent_storage.postgres.task_io import task_io_deadline

from zebra_agent_worker.progress_recovery import WorkerProgressRecovery
from zebra_agent_worker.public_output_runtime import publication_lock, publication_scope


class WorkerTransientCallGate:
    """Process-local handle for one actual public callback, checked afresh on renewal.

    CLIENT must supply a durable server-negotiated admission loader and a fresh
    verified Grant loader. No production loader exists yet; constructors are not
    admission evidence and composition never manufactures an enabled Run.
    """

    def __init__(
        self,
        *,
        scope: TransientStreamScope,
        fence: LeaseFence,
        request_sequence: int,
        tasks: AgentTaskPort,
        leases: LeaseStorePort,
        load_admission: Callable[[], RunStreamAdmission | None],
        fresh_grant_expiry: Callable[[TransientStreamScope], datetime],
    ) -> None:
        if type(request_sequence) is not int or request_sequence < 0:
            raise ValueError("request_sequence must be a canonical Task position")
        self.scope, self.fence = scope, fence
        self.request_sequence = request_sequence
        self._tasks, self._leases = tasks, leases
        self._admission, self._grant = load_admission, fresh_grant_expiry
        self._issued: TransientWriterAuthorization | None = None
        self._closed = False
        self._selected_mode: StreamMode | None = None
        self._lock = RLock()

    def stream_mode(self) -> StreamMode:
        """Resolve immutable server mode; lookup failure never means legacy."""
        with publication_lock(self._lock, bounded=True), task_io_deadline(monotonic() + 2):
            if self._closed:
                raise TransientOutputUnavailable("public callback is closed")
            admission = self._admission()
            generation = self.scope.generation
            if admission is not None and (
                admission.task_id != generation.task_id or admission.run_id != generation.run_id
            ):
                raise TransientOutputUnavailable("Run admission scope mismatch")
            self._selected_mode = StreamMode.LEGACY if admission is None else admission.mode
            return self._selected_mode

    def ordinary_v2(self) -> bool:
        """Publication eligibility after trusted mode selection, never negotiation."""
        with publication_lock(self._lock, bounded=True), task_io_deadline(monotonic() + 2):
            if self._closed or self._selected_mode is None:
                raise TransientOutputUnavailable("public callback mode is unresolved")
            if self._selected_mode is StreamMode.LEGACY:
                return False
            generation = self.scope.generation
            header = self._tasks.read_task_header(generation.task_id, require_source_coverage=True)
            if (
                header is None
                or type(header.strict_coverage) is not bool
                or header.active_segment_id != generation.segment_id
            ):
                raise TransientOutputUnavailable("public callback privacy is unknown")
            return header.strict_coverage is False

    def _fresh_authority(self) -> tuple[datetime, datetime]:
        if self._closed:
            raise TransientOutputUnavailable("public callback is closed")
        with task_io_deadline(monotonic() + 2):
            admission = self._admission()
            generation = self.scope.generation
            if (
                admission is None
                or admission.mode is not StreamMode.TRANSIENT_V2
                or admission.task_id != generation.task_id
                or admission.run_id != generation.run_id
            ):
                raise TransientOutputUnavailable("Run has no frozen v2 admission")
            header = self._tasks.read_task_header(generation.task_id, require_source_coverage=True)
            run = self._tasks.read_latest_run_header(generation.task_id)
            if (
                header is None
                or header.strict_coverage is not False
                or header.active_segment_id != generation.segment_id
                or run.run_id != generation.run_id
                or run.stop is not None
                or run.control_only
                or run.anchor is None
                or run.strict_coverage
            ):
                raise TransientOutputUnavailable("source does not authorize ordinary public text")
            page = self._tasks.read_event_page(
                generation.task_id,
                self.request_sequence - 1,
                through_sequence=run.highwater,
                limit=256,
                max_bytes=1_048_576,
            )
            if not page.events or page.has_more:
                raise TransientOutputUnavailable("public callback source suffix exceeds budget")
            request = page.events[0].event
            if (
                page.events[0].segment_id != generation.segment_id
                or request.actor is not EventActor.HARNESS
                or request.event_type is not EventType.MODEL_REQUEST_STARTED
                or request.payload.get("model_call_id") != generation.model_call_id
                or request.payload.get("attempt_number") != generation.attempt_number
                or request.payload.get("purpose") is not None
            ):
                raise TransientOutputUnavailable("source does not bind this public callback")
            if any(
                entry.event.event_type
                in (
                    EventType.HARNESS_ATTEMPT_STARTED,
                    EventType.SESSION_COMPLETED,
                    EventType.SESSION_FAILED,
                    EventType.SESSION_CANCELLED,
                )
                for entry in page.events[1:]
            ):
                raise TransientOutputUnavailable(
                    "public callback Attempt was superseded or Session is terminal"
                )
            if any(
                entry.event.event_type
                in (EventType.MODEL_REQUEST_STARTED, EventType.MODEL_RESPONSE_RECEIVED)
                and entry.event.payload.get("model_call_id") == generation.model_call_id
                for entry in page.events[1:]
            ):
                raise TransientOutputUnavailable("public callback source is completed or reused")
            lease = self._leases.get(generation.segment_id)
            if lease is None or lease.fence != self.fence:
                raise TransientOutputUnavailable("fresh full lease fence rejected")
            return lease.expires_at, self._grant(self.scope)

    def issue(self) -> TransientWriterAuthorization:
        with publication_lock(self._lock, bounded=True):
            lease_expiry, grant_expiry = self._fresh_authority()
            now = datetime.now(UTC)
            expiry = min(now + timedelta(seconds=30), lease_expiry, grant_expiry)
            self._issued = TransientWriterAuthorization(
                scope=self.scope,
                lease_fence=self.fence,
                gate_context_ref=str(uuid4()),
                issued_at=now,
                expires_at=expiry,
                lease_expires_at=lease_expiry,
                grant_expires_at=grant_expiry,
            )
            return self._issued

    def resolve(self, authorization: TransientWriterAuthorization) -> None:
        with publication_lock(self._lock, bounded=True):
            if self._closed or authorization is not self._issued:
                raise TransientOutputUnavailable("unknown public callback gate handle")
            lease_expiry, grant_expiry = self._fresh_authority()
            if not datetime.now(UTC) < authorization.expires_at <= min(lease_expiry, grant_expiry):
                raise TransientOutputUnavailable("activation authority changed")

    def close(self) -> None:
        if not self._lock.acquire(blocking=False):
            raise TimeoutError("public callback close would wait for authority I/O")
        try:
            self._closed = True
            self._issued = None
        finally:
            self._lock.release()


def split_transient_text(
    authorization: TransientWriterAuthorization,
    content: str,
    *,
    offset: int,
    anchor: int,
) -> Iterator[TransientTextFrame]:
    """Exact compact JSON budget includes Unicode, escaping and all identity fields."""
    fields = authorization.scope.generation.model_dump()
    while content:
        # ponytail: binary search avoids assumptions about JSON escaping; the
        # provider buffer is capped at64Ki characters, so at most16 probes/frame.
        lo, hi = 1, min(len(content), MAX_TRANSIENT_FRAME_BYTES)
        accepted: TransientTextFrame | None = None
        while lo <= hi:
            mid = (lo + hi) // 2
            try:
                frame = TransientTextFrame(
                    **fields, offset=offset, content_delta=content[:mid], durable_anchor=anchor
                )
            except ValueError:
                hi = mid - 1
            else:
                accepted = frame
                lo = mid + 1
        if accepted is None:
            raise TransientOutputUnavailable("identities leave no bounded text budget")
        yield accepted
        content = content[len(accepted.content_delta) :]
        offset += 1


class TransientDeltaSink:
    """Wrap progress.persist_with BEFORE ProgressiveEventSink observes the event."""

    def __init__(
        self,
        port: TransientOutputPort,
        open_call: Callable[[str, int], WorkerTransientCallGate],
        *,
        durable_anchor: Callable[[], int],
    ) -> None:
        self._port, self._open, self._anchor = port, open_call, durable_anchor
        self._gate: WorkerTransientCallGate | None = None
        self._auth: TransientWriterAuthorization | None = None
        self._call: tuple[str, int] | None = None
        self._offset, self._failed = 0, False
        self._v2_calls: set[tuple[str, int]] = set()
        self._stream_mode: StreamMode | None = None
        self._lock = RLock()

    def _draft_lock(self) -> AbstractContextManager[None]:
        # ponytail: reserve25% of the existing publication budget for facts and
        # failed-draft cleanup; this is a subdeadline, never a renewed budget.
        def scope(deadline: float) -> AbstractContextManager[float]:
            now = monotonic()
            return publication_scope(now + max(0, deadline - now) * 0.75)

        return public_output_lock(self._lock, scope)

    def start_public_call(self, call_id: str, attempt: int) -> None:
        """Called only by HarnessModelStep, never inferred from an event payload."""
        try:
            with self._draft_lock():
                self.close()
                self._call, self._offset, self._failed = (call_id, attempt), 0, False
                try:
                    self._gate = self._open(call_id, attempt)
                    mode = self._gate.stream_mode()
                    if self._stream_mode is not None and mode is not self._stream_mode:
                        raise TransientOutputUnavailable("frozen Run stream mode changed")
                    self._stream_mode = mode
                    if not self._gate.ordinary_v2():
                        self._call = None
                        self._gate.close()
                        self._gate = None
                        return
                    self._call = (call_id, attempt)
                    if len(self._v2_calls) >= 256:
                        self._failed = True
                        self._gate.close()
                        return  # Lane generation budget exhausted; business completion continues.
                    self._v2_calls.add(self._call)
                    generation = self._gate.scope.generation
                    if (generation.model_call_id, generation.attempt_number) != self._call:
                        raise TransientOutputUnavailable("callback gate identity mismatch")
                    self._auth = self._gate.issue()
                    self._port.activate(self._auth)
                except Exception:
                    self._failed = True
                    if self._call is not None and len(self._v2_calls) < 256:
                        self._v2_calls.add(self._call)
                    self._close_failed()
        except TimeoutError:
            self._call, self._failed = (call_id, attempt), True
            if len(self._v2_calls) < 256:
                self._v2_calls.add(self._call)
            # Preserve failed references for the full-response close; never add I/O here.

    def wrap(
        self,
        persist: Callable[[HarnessEventDraft], None],
    ) -> Callable[[HarnessEventDraft], None]:
        def sink(event: HarnessEventDraft) -> None:
            call = (event.payload.get("model_call_id"), event.payload.get("attempt_number"))
            known_call = isinstance(call[0], str) and type(call[1]) is int
            if event.event_type is EventType.MODEL_RESPONSE_DELTA and (
                call == self._call or (known_call and call in self._v2_calls)
            ):
                try:
                    with self._draft_lock():
                        if call == self._call:
                            self._publish(event)
                except TimeoutError:
                    if call == self._call:
                        self._failed = True
                        self._close_failed()
                return  # Uncertain drafts never fall back to durable v1 content.
            persist(event)  # The existing canonical sink owns its own authority/lock/budget.
            if event.event_type is EventType.MODEL_RESPONSE_RECEIVED and call == self._call:
                self._close_failed()

        return sink

    def _publish(self, event: HarnessEventDraft) -> None:
        if self._failed or self._auth is None or self._gate is None:
            return
        try:
            if datetime.now(UTC) >= self._auth.expires_at - timedelta(seconds=1):
                self._auth = self._gate.issue()
                self._port.activate(self._auth)
            content = event.payload.get("content_delta")
            if not isinstance(content, str) or not content:
                raise TransientOutputUnavailable("invalid public callback content")
            for frame in split_transient_text(
                self._auth, content, offset=self._offset, anchor=self._anchor()
            ):
                self._port.publish(self._auth, frame)
                self._offset += 1
        except Exception:
            self._failed = True
            self._close_failed()

    def _close_failed(self) -> None:
        try:
            self.close()
        except TimeoutError:
            pass  # Retain references for the next bounded close; no draft can publish.

    def close(self) -> None:
        with self._draft_lock():
            if self._gate is not None:
                self._gate.close()
                try:
                    self._port.invalidate(self._gate.scope)
                except (TransientOutputUnavailable, TimeoutError):
                    pass  # Redis authority expires; full durable response is still authoritative.
            self._gate, self._auth = None, None


TransientOutputFactory = Callable[[WorkerProgressRecovery, WorkerLease], TransientDeltaSink | None]
