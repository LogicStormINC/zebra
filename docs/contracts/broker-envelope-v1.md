# Broker envelope v1

This foundation contract is a **wakeup hint**, not an authorization credential or
an instruction to activate RabbitMQ. Both repositories keep an identical standalone
Pydantic v2 implementation and identical examples/schema without cross-repository
imports. No broker library, consumer, publisher, routing activation, database
migration, or runtime composition is introduced.

## Wire contract

All fields are required; only `causation_id` and `traceparent` may be null.
Models and nested models are frozen and reject unknown fields. Integers are strict:
booleans, strings and floats are not integers. Schema version is exactly 1.
IDs are opaque strings, 1–256 characters, nonblank, without C0/C1 controls;
deployment namespaces have a 128-character maximum. Whitespace is not trimmed.
UUID strings use canonical lowercase, hyphenated hexadecimal spelling.
Timestamps use RFC3339 uppercase T/Z or numeric offsets and must describe a valid
calendar instant; leap seconds are not supported by Python datetime.
Trace context accepts version 00 only, lowercase hexadecimal and nonzero trace/span
IDs. Trace flags remain the full W3C byte; unknown flag bits are not authority.

| Message type | Reference kind | Scope | Additional constraint |
| --- | --- | --- | --- |
| trench.ai.turn.ready | trench_turn | principal | aggregate_id = operation_id |
| zebra.session.command.ready | zebra_command | principal | accepted_event_id UUID and accepted_sequence > 0 |
| trench.source.fetch.ready | source_fetch_command | principal or shared_source | aggregate_id may differ |

Every `payload_ref.id` equals `operation_id`. Zebra accepted-event evidence is
required for Zebra messages and forbidden for other messages. References contain
only a typed kind and opaque ID: no payload dictionaries, credentials, dynamic
tables, SQL, or URL reference fields.

## Decoder versus JSON Schema

`parse_broker_envelope(raw: bytes)` rejects inputs over 16,384 bytes before decoding,
invalid UTF-8/JSON, duplicate object keys, nonfinite numbers, and JSON structures
deeper than eight containers (root container counts as one). It then validates the
typed envelope. It returns a discriminated TurnEnvelope, ZebraCommandEnvelope or
SourceFetchEnvelope. It does not resolve references or trust supplied identity.

`broker_envelope_json_schema()` exports the committed JSON Schema shape.
The schema cannot enforce sibling-field equality, raw byte limits, duplicate
keys or decoder depth. Custom validators additionally check nonblank/control-free
IDs, actual timestamp validity and nonzero trace/span IDs. Consumers must use the
decoder, not schema validation alone, as their wire boundary.

Runtime policy must independently verify deployment, principal/service identity,
database object scope, accepted-event provenance and current wake generation.
A syntactically valid scope or accepted event does not prove permission.
Callers should not log raw input or Pydantic validation error input values:
malformed inputs can contain credentials even though this contract forbids them.

## Reproducibility and checks

The schema is generated from `broker_envelope_json_schema()` using
`json.dumps(schema, indent=2, sort_keys=True) + "\n"`.
The examples file includes valid Turn, Zebra, private-source and shared-source
messages plus invalid envelopes. Tests compare generated schema to the checked-in
artifact, validate examples, and compare both artifact copies when the sibling
checkout is available. Standalone checkout testing does not require that sibling.

Zebra: `.venv/bin/python -m pytest tests/agent_core/test_broker_envelope.py`

Trench: `python -m pytest tests/test_broker_envelope.py`
