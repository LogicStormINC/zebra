"""Bounded public facts: no tool execution, mutation retries or private reasoning."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, replace
from hashlib import sha256
from re import fullmatch
from threading import Event, RLock, Thread, Timer, current_thread
from typing import Any

from agent_core.contracts.public_output import EvidenceBasis, PublicOperationFacts, PublicReadFacts
from agent_core.contracts.public_output import PublicOutputPolicy as PublicOutputPolicy
from agent_core.domain.events import EventActor, EventType
from agent_core.harness.model_commentary import ModelCommentaryPublisher, plan_response
from agent_core.harness.model_response_progress import observe_model_response
from agent_core.harness.models import HarnessEventDraft
from agent_core.harness.public_expression import PublicExpression
from agent_core.harness.public_output_lifecycle import (
    PublicationScope,
    PublicOutputClosed,
    close_public_output,
    current_public_output_deadline,
    public_output_lock,
)
from agent_core.harness.public_output_publication import narration_draft
from agent_core.ports.worker_progress import WorkerProgressState


class ProgressiveEventSink:
    """Serialize real events and fallback messages through the SAME fenced sink.

    ponytail: one wait timer and one short fact-batch timer, never a broadcaster Agent;
    max_outputs bounds narration. Business-specific facts come from Host receipts.
    """

    def __init__(
        self,
        sink: Callable[[HarnessEventDraft], None],
        *,
        user_input: str,
        policy: PublicOutputPolicy,
        prior_outputs: Sequence[Mapping[str, Any]] = (),
        attempt_number: int = 1,
        expression: PublicExpression | None = None,
        recovery_state: WorkerProgressState | None = None,
        output_published: Callable[[str], bool] | None = None,
        receipts_covered: Callable[[tuple[str, ...]], frozenset[str]] | None = None,
        emission_scope: PublicationScope | None = None,
    ) -> None:
        self._sink = sink
        self._emission_scope = emission_scope
        self.policy = policy
        self._attempt = attempt_number
        self._expression = expression
        self._chinese = any("\u4e00" <= char <= "\u9fff" for char in user_input)
        self._seen = {str(item["output_id"]) for item in prior_outputs if item.get("output_id")}
        self._covered_receipts = {
            str(ref)
            for item in prior_outputs
            if item.get("phase") == "evidence"
            for ref in item.get("evidence_refs", ())
        }
        self._meaningful = any(item.get("meaningful") is True for item in prior_outputs)
        self._evidence_published = any(
            item.get("phase") == "evidence" and item.get("evidence_basis") is not None
            for item in prior_outputs
        )
        self._result_published = any(
            item.get("evidence_basis") == "verified_result" for item in prior_outputs
        )
        self._started = any(item.get("phase") == "started" for item in prior_outputs)
        self._model_spoke = False
        commentary = len(
            {
                str(item["output_id"])
                for item in prior_outputs
                if item.get("phase") == "model_commentary" and item.get("output_id")
            }
        )
        self._published_count = len(self._seen) - commentary
        self._output_published = output_published or (lambda _: False)
        self._receipts_covered = receipts_covered or (lambda _: frozenset())
        self._commentary = ModelCommentaryPublisher(
            sink,
            self._output_published,
            recovery_state.commentary_reserved_count if recovery_state else commentary,
        )
        if recovery_state is not None:
            if prior_outputs or recovery_state.attempt_number != attempt_number:
                raise ValueError("Worker progress conflicts with sink recovery identity")
            self._chinese = (
                recovery_state.chinese if recovery_state.chinese is not None else self._chinese
            )
            self._model_spoke = recovery_state.model_spoke
            self._started = recovery_state.started
            self._meaningful = recovery_state.meaningful
            self._evidence_published = recovery_state.evidence_published
            self._result_published = recovery_state.result_published
            self._published_count = recovery_state.published_count
        self._pending: dict[str, PublicReadFacts | PublicOperationFacts | None] = {}
        self._active: set[str] = set()
        self._timer: Timer | None = None
        self._timer_generation = 0
        self._evidence_timer: Timer | None = None
        self._evidence_generation = 0
        self._running_timer: Thread | None = None
        self._closing = Event()
        self._lock = RLock()
        self._timer_error: Exception | None = None
        self._closed = recovery_state.terminal if recovery_state is not None else False

    def __call__(self, event: HarnessEventDraft) -> None:
        with public_output_lock(
            self._lock, self._emission_scope, self._closing if self._emission_scope else None
        ):
            if self._timer_error is not None:
                raise self._timer_error
            if event.event_type is EventType.MODEL_REQUEST_STARTED:
                if not self._closed:
                    self._publish_pending()
                event = replace(
                    event, payload={**event.payload, "public_output_policy": asdict(self.policy)}
                )
            if event.event_type is EventType.MODEL_RESPONSE_RECEIVED:
                event = replace(
                    event, payload=plan_response(event.payload, self._commentary.reserved)
                )
            self._sink(event)  # append-before-push and authority checking remain downstream
            if not self._closed:
                self._observe(event)

    def _observe(self, event: HarnessEventDraft) -> None:
        payload, kind = event.payload, event.event_type
        if kind is EventType.TESTS_COMPLETED:
            metadata = payload.get("metadata")
            receipt = metadata.get("execution_receipt") if isinstance(metadata, Mapping) else None
            if isinstance(receipt, Mapping):
                self._observe(
                    HarnessEventDraft(
                        EventType.TOOL_EXECUTION_COMPLETED
                        if receipt.get("status") == "executed"
                        else EventType.TOOL_EXECUTION_FAILED,
                        EventActor.TOOL,
                        {
                            "tool_call_id": receipt.get("tool_call_id"),
                            "status": receipt.get("status"),
                            "metadata": {"public_facts": receipt.get("public_facts")},
                        },
                    )
                )
            return
        call_id = str(payload.get("tool_call_id", payload.get("model_call_id", "")))
        if kind is EventType.MODEL_REQUEST_STARTED:
            self._active.add(f"model:{call_id}")
            self._arm_wait()
        elif kind is EventType.MODEL_RESPONSE_DELTA:
            delta = payload.get("content_delta")
            self._model_spoke |= isinstance(delta, str) and bool(delta.strip())
            self._cancel_timer()
            self._arm_wait()  # First text is progress, not a terminal provider receipt.
        elif kind is EventType.MODEL_RESPONSE_RECEIVED:
            observe_model_response(self, event)
        elif kind in {EventType.TOOL_CALL_PROPOSED, EventType.TOOL_EXECUTION_STARTED}:
            if not self._started:
                self._started = True
                if not self._model_spoke:
                    name = payload.get("tool_name")
                    safe_name = isinstance(name, str) and fullmatch(r"[\w./:-]{1,128}", name)
                    content = self._text(
                        "已提出一项操作，仍需通过权限检查；目前尚无成功结果。",
                        "An operation is proposed, subject to permission checks; "
                        "there is no successful result yet.",
                    )
                    if safe_name:
                        content = (
                            self._text(
                                f"已选择 `{name}`，准备执行并核对返回结果；仍需通过权限检查。",
                                f"Selected `{name}`; preparing to execute and check its result, "
                                "subject to permission checks.",
                            )
                            if kind is EventType.TOOL_CALL_PROPOSED
                            else self._text(
                                f"已开始执行 `{name}`，正在等待它返回；取得回执后会先报告发现。",
                                f"Started `{name}` and awaiting its receipt; "
                                "confirmed findings will be shared as they arrive.",
                            )
                        )
                    # A tool name identifies the operation, not confirmed business evidence.
                    self.publish(
                        "started",
                        "commentary",
                        "started",
                        content,
                        evidence_refs=[call_id] if safe_name and call_id else [],
                    )
            if kind is EventType.TOOL_EXECUTION_STARTED:
                self.operation_started(call_id)
        elif kind in {EventType.TOOL_EXECUTION_COMPLETED, EventType.TOOL_EXECUTION_FAILED}:
            self._stop_wait(f"tool:{call_id}")
            if kind is EventType.TOOL_EXECUTION_FAILED:
                self.publish(
                    f"failure:{call_id}",
                    "commentary",
                    "recovery",
                    self._text(
                        "有一项操作未得到成功回执。我会检查可用证据与安全替代路径；不会盲目重试结果未知的写操作。",
                        "One operation has no successful receipt. I will check available evidence "
                        "and safe alternatives, not retry an uncertain write blindly.",
                    ),
                    evidence_refs=[call_id],
                )
                return
            if payload.get("status") != "executed":
                return
            if call_id in self._covered_receipts or call_id in self._receipts_covered((call_id,)):
                return
            metadata = payload.get("metadata")
            facts = metadata.get("public_facts") if isinstance(metadata, Mapping) else None
            # Adapter-attested facts are display data, never model instructions.
            if len(self._pending) >= 32:
                self._publish_pending()
            try:
                verified: PublicReadFacts | PublicOperationFacts | None = None
                if call_id and isinstance(facts, Mapping) and facts.get("kind") == "operation":
                    operation = PublicOperationFacts.model_validate(facts)
                    if operation.tool_call_id == call_id and (
                        payload.get("tool_name") is None
                        or payload["tool_name"] == operation.receipt.tool_name
                    ):
                        verified = operation
                elif call_id:
                    verified = PublicReadFacts.model_validate(facts)
            except ValueError:
                verified = None  # Legacy/unproven summaries do not establish business evidence.
            self._pending[call_id] = verified
            if verified and (
                not self._evidence_published
                or verified.evidence_basis == "verified_result"
                and not self._result_published
            ):
                self._publish_pending()
            elif (
                isinstance(verified, PublicReadFacts)
                and self._evidence_timer is None
                and not self._closing.is_set()
            ):
                self._evidence_timer = Timer(
                    self.policy.delta_seconds,
                    self._wait_elapsed,
                    args=(self._evidence_generation,),
                    kwargs={"evidence": True},
                )
                self._evidence_timer.daemon = True
                self._evidence_timer.start()
        elif kind is EventType.ANSWER_COMMITTED:
            self._closed = True
            self._pending.clear()
            self._active.clear()
            self._cancel_timer()
            self._cancel_evidence_timer()

    def _publish_pending(self) -> None:
        self._cancel_evidence_timer()
        while self._pending:
            self._publish_evidence()

    def _publish_evidence(self) -> None:
        if not self._pending:
            return
        basis = next(
            (
                item.evidence_basis
                for item in self._pending.values()
                if isinstance(item, PublicReadFacts)
            ),
            None,
        )
        refs = [
            ref
            for ref, item in self._pending.items()
            if not isinstance(item, PublicReadFacts) or item.evidence_basis == basis
        ]
        summaries = list(
            dict.fromkeys(item.summary for ref in refs if (item := self._pending[ref]) is not None)
        )
        business_summaries = {
            item.summary for ref in refs if isinstance(item := self._pending[ref], PublicReadFacts)
        }
        for ref in refs:
            self._pending.pop(ref)
        content = (
            "\n\n".join(summaries)
            if summaries
            else self._text(
                f"已收到 {len(refs)} 项成功工具回执，正在整理并核对；这不代表已覆盖全部数据。",
                f"Received {len(refs)} successful tool receipts. "
                "I am consolidating and checking them; this does not imply complete coverage.",
            )
        )
        fingerprint = sha256("\n".join(refs).encode()).hexdigest()[:24]
        if f"public:{self._attempt}:evidence:{fingerprint}" in self._seen:
            return
        if len(content) > self.policy.max_characters:
            suffix = self._text(
                "另有回执未在此处展开；这不是完整数据覆盖。",
                "More receipts are omitted here; this is not complete data coverage.",
            )
            bounded: list[str] = []
            for summary in summaries:
                if len("\n\n".join([*bounded, summary, suffix])) <= self.policy.max_characters:
                    bounded.append(summary)
            summaries = [*bounded, suffix] if bounded else []
            content = "\n\n".join([*bounded, suffix])
        meaningful = bool(business_summaries.intersection(summaries))
        persisted = self.publish(
            f"evidence:{fingerprint}",
            "result" if meaningful and basis == "verified_result" else "commentary",
            "evidence",
            content,
            meaningful=meaningful,
            evidence_basis=basis if meaningful else None,
            evidence_refs=refs,
        )
        if persisted:
            self._covered_receipts.update(refs)
            self._evidence_published = self._evidence_published or meaningful
            self._result_published |= meaningful and basis == "verified_result"
        if (
            persisted
            and meaningful
            and len(summaries) > 1
            and self._expression is not None
            and not self._closed
            and not self._closing.is_set()
            and self._published_count < self.policy.max_outputs
        ):
            expressed = self._expression.express(
                summaries, chinese=self._chinese, deadline=current_public_output_deadline()
            )
            if (
                expressed is not None
                and expressed[0] != content
                and len(expressed[0]) <= self.policy.max_characters
            ):
                self.publish(
                    f"expression:{fingerprint}",
                    "result" if basis == "verified_result" else "commentary",
                    "evidence",
                    expressed[0],
                    meaningful=True,
                    evidence_basis=basis,
                    evidence_refs=refs,
                    origin="model",
                    model_call_id=expressed[1],
                    replaces_output_id=f"public:{self._attempt}:evidence:{fingerprint}",
                )

    def publish(
        self,
        output_id: str,
        kind: str,
        phase: str,
        content: str,
        *,
        meaningful: bool = False,
        evidence_basis: EvidenceBasis | None = None,
        evidence_refs: list[str] | None = None,
        replaces_output_id: str | None = None,
        origin: str = "system",
        model_call_id: str | None = None,
    ) -> bool:
        with public_output_lock(self._lock, self._emission_scope):
            output_id = f"public:{self._attempt}:{output_id}"
            if (
                self._closed
                or self._closing.is_set()
                or output_id in self._seen
                or self._published_count >= self.policy.max_outputs
                or self._output_published(output_id)
            ):
                return False
            self._sink(
                narration_draft(
                    output_id,
                    kind,
                    phase,
                    content,
                    attempt=self._attempt,
                    policy=self.policy,
                    meaningful=meaningful,
                    evidence_basis=evidence_basis,
                    evidence_refs=evidence_refs,
                    replaces_output_id=replaces_output_id,
                    origin=origin,
                    model_call_id=model_call_id,
                )
            )
            self._seen.add(output_id)
            self._published_count += 1
            self._meaningful = self._meaningful or meaningful
            return True

    def operation_started(self, call_id: str) -> None:
        """Observe an admitted, durably scheduled Effect without minting another event."""
        with public_output_lock(self._lock, self._emission_scope):
            if not self._closed:
                self._active.add(f"tool:{call_id}")
                self._arm_wait()

    def observe_operation_result(self, event: HarnessEventDraft) -> None:
        """Observe a store-owned terminal receipt, without appending it again."""
        if event.event_type not in {
            EventType.TOOL_EXECUTION_COMPLETED,
            EventType.TOOL_EXECUTION_FAILED,
        }:
            raise ValueError("external observation requires a terminal tool result")
        with public_output_lock(self._lock, self._emission_scope):
            if not self._closed:
                if self._timer_error is not None:
                    raise self._timer_error
                self._observe(event)

    def _text(self, chinese: str, english: str) -> str:
        return chinese if self._chinese else english

    def _arm_wait(self) -> None:
        if self._timer is None and self._active and not self._closing.is_set():
            self._timer = Timer(
                self.policy.wait_seconds, self._wait_elapsed, args=(self._timer_generation,)
            )
            self._timer.daemon = True
            self._timer.start()

    def _wait_elapsed(self, generation: int, *, evidence: bool = False) -> None:
        try:
            with public_output_lock(self._lock, self._emission_scope, self._closing):
                expected = self._evidence_generation if evidence else self._timer_generation
                if generation != expected or self._closed or self._timer_error is not None:
                    return
                self._running_timer = current_thread()
                if evidence:
                    self._publish_pending()
                    return
                self._timer = None
                if not self._active:
                    return
                fingerprint = sha256("\n".join(sorted(self._active)).encode()).hexdigest()[:24]
                self.publish(
                    f"wait:{fingerprint}",
                    "status",
                    "waiting",
                    self._text(
                        "仍在等待当前操作返回，暂时没有新的已确认结果。连接心跳不代表任务取得进展。",
                        "Still waiting for the current operation; "
                        "there is no new confirmed result. "
                        "Connection heartbeats are not execution progress.",
                    ),
                )
        except PublicOutputClosed:
            pass  # An unadmitted callback is stopped, not a failed durable write.
        except Exception as error:
            self._timer_error = error
        finally:
            self._running_timer = None

    def _stop_wait(self, key: str) -> None:
        self._active.discard(key)
        if not self._active:
            self._cancel_timer()

    def _cancel_timer(self) -> None:
        self._timer_generation += 1
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def close(self) -> None:
        close_public_output(
            self._lock,
            self._closing,
            lambda: (self._timer, self._evidence_timer, self._running_timer),
            self._finish_close,
        )
        if self._timer_error is not None:
            raise self._timer_error

    def _finish_close(self) -> None:
        self._closed = True
        self._pending.clear()
        self._active.clear()
        self._cancel_timer()
        self._cancel_evidence_timer()

    def _cancel_evidence_timer(self) -> None:
        self._evidence_generation += 1
        if self._evidence_timer is not None:
            self._evidence_timer.cancel()
            self._evidence_timer = None
