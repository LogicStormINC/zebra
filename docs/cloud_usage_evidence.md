# Cloud Agent usage evidence (CLOUD-USER-USAGE-01)

`GET /usage?days=7|30` is a signed-Host, `event.read` Cloud API. It is not a
billing ledger. The authenticated Host Grant must contain exactly one opaque
`principal` resource. The PostgreSQL read selects only Tasks whose latest
binding snapshot matches the Grant's Host app, namespace, workspace, and
principal; a caller cannot select a principal through query parameters.

The time window is UTC calendar days, including today. The response carries
`schema_version=1`, `source=committed_cloud_events`, `period`, `totals`,
`daily`, `daily_models`, `models`, `tools`, and `tasks`. Counts come only from
committed `model_response_received`, `tool_execution_completed` /
`tool_execution_failed`, and `user_message_received` Events. The read is
bounded to 100,000 Events per request and does not return message text or
private provider payloads.

Token fields are provider-reported values. `total_tokens` uses the provider's
total if present, otherwise the sum of both known input and output fields;
it does not use `estimated_input_tokens`. `reasoning_tokens` is a subset of
output, never added again to the total. A model response without enough token
data increments `unmetered_calls` instead of becoming a zero-cost call.

Trench's `/api/trench-ai/usage` obtains a fresh Broker grant for the current
authenticated viewer, then forwards the read. The reusable
`AgentUsageAnalytics` React component accepts the API snapshot as a controlled
prop; it does not own Host authentication or pricing. A replaced conversation
pointer does not erase older Task usage because aggregation reads immutable
Task bindings and Events, not Trench's current conversation pointer.

Billing follow-up: define a versioned price/rate and entitlement policy in
the Host, reconcile metered and unmetered calls, and create an immutable
charge ledger keyed to model-call identity before exposing costs, credits,
weekly limit percentages, or invoices. Historical Tasks without binding
snapshots and upstream calls without token data require explicit coverage and
reconciliation policy. No cross-Host identity merge is implied.
