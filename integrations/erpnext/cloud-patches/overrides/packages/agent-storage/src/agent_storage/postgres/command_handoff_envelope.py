from uuid import UUID

from agent_core.contracts.broker_envelope import (
    PrincipalScope,
    ZebraCommandEnvelope,
    parse_broker_envelope,
)


def parse_handoff_envelope(
    raw_body, scope, deployment_namespace, accepted_event_id, required_scope_mode
):
    if not isinstance(scope, PrincipalScope) or not isinstance(accepted_event_id, UUID):
        raise ValueError("handoff requires trusted principal scope and canonical Event UUID")
    if required_scope_mode not in (None, "broker", "fallback"):
        raise ValueError("invalid required command scope mode")

    envelope = None
    if raw_body is not None:
        try:
            envelope = parse_broker_envelope(raw_body)
            if (
                not isinstance(envelope, ZebraCommandEnvelope)
                or envelope.scope != scope
                or envelope.deployment_namespace != deployment_namespace
                or envelope.accepted_event_id != str(accepted_event_id)
            ):
                raise ValueError("scope or identity mismatch")
        except ValueError:
            raise ValueError("invalid command handoff envelope or scope") from None
    return envelope
