# Trench concurrent session activity — 2026-10-28

Task: TRN-MULTI-SESSION-SPIN-SYNC-20261028. Owner: Luke Ding; executor: Codex.

## Paired source

Owning repository: LogicStormINC/Trench, main.
Fix: 6a1a8b8 (TRN-MULTI-SESSION-SPIN-20261028).
[Fix and deterministic checks](https://github.com/LogicStormINC/Trench/commit/6a1a8b8).
[Detailed package hashes and reproduction](https://github.com/LogicStormINC/Trench/blob/6a1a8b8/docs/TRN_MULTI_SESSION_ACTIVITY.md).

The Trench SQL store maps every current user/workspace active Turn independently
by conversation key, but its HTTP summary model omitted activeTurn. FastAPI
removed the field from every item. Trench frontend overlaid only the selected
conversation's observer state, causing all other running badges to disappear.

The additive typed summary retains turn_id/status/updated_at_ms under the existing
activeTurn JSON key. This handles any number of list items, requires no extra
queries and does not change execution, Worker, SDK or stream state.

## Fresh verification

- 3 and 12 concurrent sessions through real SQLite store and actual HTTP route;
  idle session, repeated reads, foreign user/workspace filtering, independent
  completed/failed/cancelled updates. Red before correction, green after it.
- Actual sidebar component: 12 spinners, select idle session, finish three,
  retain nine spinners and retain them after unmount/reload.
- 53 focused API checks plus 78 existing main compatibility checks passed.
- Full Trench frontend: 75 files / 532 tests passed. TypeScript, focused ESLint,
  Ruff (existing camelCase DTO N815 baseline excluded) and diff checks passed.
- No live production concurrency/load or deployment claim; no original Run writes.

## Package and branch synchronization boundary

User explicitly requested GitHub source/package files only, not npm registry.
All five Trench vendored Zebra 0.1.0 tarballs match GitHub byte-for-byte; no SDK
behavior changed and no repack is needed. Trench main publication also includes
its two existing committed ancestors 8feacbf/b159d1a, including @noble/hashes 2.4.0
and the corresponding manifest/lockfile/browser SHA-256 source and tests.

The user requested this receipt on BOTH cloud-agent-trench and cloud-agent.
This is a narrow documentation-only maintenance exception to the frozen branch
policy. The cloud-agent-trench-archive-2026-10-20 tag stays unchanged. Runtime and
SDK source on each Zebra branch remain at their own current version; this host
API defect does not justify merging generic Cloud development into the archived
compatibility branch or rebuilding unrelated npm packages.
