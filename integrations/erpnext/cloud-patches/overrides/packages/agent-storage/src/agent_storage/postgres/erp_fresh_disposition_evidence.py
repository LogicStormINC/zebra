from agent_core.contracts.broker_envelope import ZebraCommandEnvelope as ZebraCommandEnvelope
from agent_core.contracts.turn_events import validate_turn_identity
from agent_core.domain.task_bindings import host_context_digest
from agent_storage.postgres.command_wakeup_receipts import _validate
from agent_storage.postgres.command_wakeup_recovery_proof import MAX_GENERATION, recovery_approval


def _binding_identity(binding, event, command):
    host = binding.host_capability
    context = host.host_context
    if (
        context is None
        or (host.host_app_id, host.namespace_id) != ("erpnext", "erpnext")
        or host.grant_digest != host_context_digest(context)
    ):
        raise ValueError("fresh disposition requires an ERP stored binding")

    def refs(kind):
        return [r.resource_id for r in context.resource_refs if r.resource_type == kind]

    runs, principals, threads = refs("run"), refs("principal"), refs("thread")
    if (
        len(runs) != 1
        or len(principals) != 1
        or len(threads) != 1
        or runs[0] != command.payload.get("run_id")
        or command.payload.get("thread_id") != binding.task_id
    ):
        raise ValueError("fresh disposition Run attribution conflicts")
    return {
        "task_id": binding.task_id,
        "binding_revision": binding.binding_revision,
        "binding_digest": binding.binding_digest,
        "run_id": runs[0],
        "principal": principals[0],
        "thread_id": threads[0],
        "tenant_id": context.namespace_id,
        "workspace_id": context.workspace_ref,
    }


def _turn(connection, namespace, event, command, floor, input_event_id=None, *, command_loader):
    # ponytail: metadata O(Turn length); unknown events deny proof. A native indexed
    # Turn metadata reader can replace this when the conservative ceiling grows.
    opening = connection.execute(
        """SELECT event_id,sequence,actor,causation_id,payload->>'origin' AS origin,
           payload->>'turn_id' AS turn_id,payload->'turn_index' AS turn_index
           FROM session_events WHERE deployment_namespace=%s AND session_id=%s
             AND event_type='user_message_received' AND sequence<=%s
           ORDER BY sequence DESC LIMIT 1""",
        (namespace, event.session_id, floor),
    ).fetchone()
    if (
        opening is None
        or opening["actor"] != "user"
        or opening["origin"] != "human"
        or type(opening["turn_index"]) is not int
        or opening["turn_index"] < 0
    ):
        raise ValueError("fresh disposition has no canonical human Turn")
    turn_id = validate_turn_identity(opening["turn_id"])
    if command.extension_turn_id not in (None, turn_id):
        raise ValueError("fresh disposition Turn attribution conflicts")
    if command.kind.value == "message":
        if (
            opening["causation_id"] != event.event_id
            or opening["sequence"] <= event.sequence
            or (input_event_id is not None and opening["event_id"] != input_event_id)
        ):
            raise ValueError("fresh disposition MESSAGE input attribution conflicts")
    elif command.kind.value != "run" or opening["sequence"] >= event.sequence:
        raise ValueError("fresh disposition requires an unstarted RUN or MESSAGE")
    rows = connection.execute(
        """SELECT event_id,sequence,event_type,actor FROM session_events
           WHERE deployment_namespace=%s AND session_id=%s AND sequence>%s AND sequence<=%s
           ORDER BY sequence""",
        (namespace, event.session_id, opening["sequence"], floor),
    ).fetchall()
    for row in rows:
        if (
            row["event_type"] == "task_prepared"
            and row["sequence"] == 2
            and opening["sequence"] == 1
            and opening["turn_index"] == 0
            and row["actor"] == "harness"
        ):
            continue
        if row["event_type"] != "session_command_accepted":
            raise ValueError("fresh disposition Turn has execution or unknown evidence")
        _, admitted = command_loader(connection, namespace, row["event_id"])
        if admitted.kind.value != "run" or admitted.extension_turn_id not in (None, turn_id):
            raise ValueError("fresh disposition Turn has a conflicting command")
    return {
        "turn_id": turn_id,
        "turn_index": opening["turn_index"],
        "opening_event_id": str(opening["event_id"]),
        "opening_sequence": opening["sequence"],
    }


def _modern(connection, namespace, event, pending, receipt, scope, *, fence_fields):
    from agent_storage.postgres.command_wakeup_handoff import _check_inbox

    if (
        pending["origin"] != "live"
        or receipt is None
        or receipt["status"] != "accepted"
        or receipt["started_event_id"] is not None
        or receipt["handled_event_id"] is not None
        or type(receipt["execution_floor_sequence"]) is not int
        or receipt["execution_floor_sequence"] < event.sequence
        or receipt["wake_generation"] != pending["current_generation"]
        or any(
            receipt[k] != pending[k]
            for k in ("scope_key", "command_id", "accepted_event_id", "session_id")
        )
    ):
        raise ValueError("fresh disposition has no unstarted accepted handoff")
    generation = pending["current_generation"]
    if type(generation) is not int or not 0 <= generation <= MAX_GENERATION:
        raise ValueError("fresh disposition generation exceeds native bound")
    outboxes = connection.execute(
        """SELECT * FROM broker_outbox WHERE deployment_namespace=%s AND scope_key=%s
             AND operation_id=%s AND message_type='zebra.session.command.ready'
           ORDER BY wake_generation""",
        (namespace, pending["scope_key"], pending["command_id"]),
    ).fetchall()
    if len(outboxes) != generation + 1:
        raise ValueError("fresh disposition generation history is incomplete")
    for index, outbox in enumerate(outboxes):
        if outbox["wake_generation"] != index:
            raise ValueError("fresh disposition generation history has a gap")
        _validate(connection, namespace, pending, outbox, scope, None)
        approval = recovery_approval(
            connection, ZebraCommandEnvelope.model_validate(outbox["envelope_json"])
        )
        if approval is None:
            continue
        previous = approval["previous_receipt"]
        if (
            approval["reason"] not in {"expired_unstarted", "published_no_handoff"}
            or approval["coverage_proof"] is not None
            or not event.sequence
            <= approval["approved_stream_sequence"]
            <= receipt["execution_floor_sequence"]
        ):
            raise ValueError("fresh disposition history contains uncertain execution")
        if previous is None:
            if approval["reason"] != "published_no_handoff":
                raise ValueError("fresh disposition recovery receipt is missing")
        elif (
            approval["reason"] != "expired_unstarted"
            or previous.get("status") != "accepted"
            or previous.get("wake_generation") != index - 1
            or previous.get("started_event_id") is not None
            or previous.get("handled_event_id") is not None
            or previous.get("execution_floor_sequence") != approval["approved_stream_sequence"]
            or any(
                previous.get(k) != str(pending[k])
                for k in ("accepted_event_id", "session_id", "command_id", "scope_key")
            )
            or any(previous.get(k) is None for k in fence_fields)
        ):
            raise ValueError("fresh disposition recovery receipt is not unstarted")
    if _check_inbox(connection, namespace, pending, outboxes[-1]) != "accepted":
        raise ValueError("fresh disposition requires its exact accepted Inbox")
    if (
        connection.execute(
            (
                "SELECT 1 FROM command_retirements WHERE deployment_namespace=%s "
                "AND accepted_event_id=%s\n           UNION ALL SELECT 1 FROM comm"
                "and_control_receipts\n           WHERE deployment_namespace=%s AN"
                "D accepted_event_id=%s LIMIT 1"
            ),
            (namespace, event.event_id, namespace, event.event_id),
        ).fetchone()
        is not None
    ):
        raise ValueError("fresh disposition conflicts with retirement or control")
    return outboxes[-1]
