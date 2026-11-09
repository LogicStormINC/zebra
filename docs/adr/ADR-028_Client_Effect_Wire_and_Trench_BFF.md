# ADR-028: Client Effect Wire and Trench BFF

- Status: Accepted for the R07 pilot
- Date: 2026-09-20
- Protocol: `client-effect-v1`

## Decision

Trench browsers never receive or send a Zebra HostGrant. The authenticated
Trench BFF exchanges its Host authority independently for every Zebra client
runtime request. The browser holds only the bounded Zebra Client Session
credential and the active controller fence.

An executable Client Effect must carry all of these immutable coordinates:

- Effect ID, action name and canonical action-contract digest;
- Task ID and Run ID;
- Client Session ID as the Surface instance;
- expected UI revision;
- deadline;
- request digest and idempotency key.

Sparse historical Effect events remain readable, but are never projected as
executable actions. The client validates every coordinate before invoking a
registered handler. A duplicate Effect returns the persisted receipt. A page
refresh during an in-flight handler reports `unavailable` and requires a new
Agent decision; it does not execute the handler again.

Only the active fenced controller may submit receipts. A Trench turn change
releases the previous controller and opens, mounts and binds a new Surface for
the new Run. Multiple tabs therefore compete through the durable Zebra fence,
not through browser-local election.

## Shared State ownership

AG-UI `state` is not inherently client-owned. Existing server-owned run
configuration remains unchanged when no frontend mount is declared. A command
becomes client-owned only when `frontendAppId`, `clientSessionId` or
`uiRevision` is explicitly present, or when it declares frontend tools.

For a declared frontend mount:

- top-level state keys must match published Readable contracts;
- restricted JSON Schema and per-readable byte limits are enforced;
- sensitive fields are redacted before persistence;
- the admitted snapshot and digest are persisted in the command event;
- Worker restart recovers only that admitted, redacted snapshot;
- AG-UI projects it under the `/client` namespace with `host_frontend`
  ownership.

Trench business facts remain Trench-owned. Zebra progress remains
Zebra-owned. The R07 pilot exposes only navigation, presentation and local
filter/range actions; it does not publish a business-write action.

## Trench pilot lifecycle

The dashboard bridge resolves the current durable Turn, then calls the Trench
BFF to open a Client Session, mount the published `trench-web` profile and bind
the exact Task/Run before polling durable pending Effects. Each transition uses
a fresh HostGrant. Session credentials and receipts live in `sessionStorage`,
so refresh can replay a receipt but cannot share it across tabs.

The profile must be published and bound by a platform operator before enabling
the bridge. The release manifest records its revision and digest. Missing
profile configuration fails closed with `client_profile_unconfigured`.

## Failure and rollback

- malformed, expired, wrong-Run, wrong-Surface or stale-revision Effects do not
  execute;
- a lost receipt response is retried with the same receipt and idempotency key;
- three consecutive bridge failures discard the local Surface and renegotiate;
- unload attempts an explicit release, while the five-minute controller lease
  remains the crash fallback;
- disabling Zebra Client Integration removes client tools without affecting
  backend task execution;
- removing the Trench bridge stops new mounts and leaves existing leases to
  expire; no database rollback is required.

## Evidence boundary

R07 deterministic API, Worker, projection and TypeScript tests prove the wire,
recovery and duplicate semantics. Trench MockTransport and frontend tests prove
the BFF sequence and action validation. Real PostgreSQL and browser acceptance
remain separate G2/R14 evidence and must not be inferred from these tests.
