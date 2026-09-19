# Cloud Release Evidence

## Purpose

The release gate separates deterministic correctness, production composition,
real dependencies, fault injection, cross-repository behavior and external
services. A process exit alone is not release evidence. Every executable gate
writes a credential-free `gate-result.json`; pytest gates also write JUnit.

## Commands

```bash
make test-cloud-contracts      # L1 deterministic contracts
make test-cloud-composition    # L2 production composition roots
make test-cloud-integration    # L3 PostgreSQL/MinIO/Redis recovery matrix
make test-cloud-faults         # L4 real PostgreSQL fault injection
make test-trench-e2e           # L5 deployed Trench/Zebra acceptance
make test-gvisor-runtime       # L3 real task isolation
make test-redis-agent-memory   # L6 explicitly authorized external provider
```

Set `EVIDENCE_ROOT` to an artifact directory outside the repository when
collecting a candidate. Each result binds the current Git SHA, clean-worktree
state, lock/Compose digests, dependency versions, duration and outcome. Commands
are represented by a digest, never copied into evidence where an argument could
contain a credential.

The L3 matrix covers application composition, Redis live fanout, PostgreSQL
PITR, S3 recovery and full recovery restore. L4 exercises transaction rollback,
lease clocks/fencing and task-lease races against real PostgreSQL. The Trench
workflow is manual on the protected `trench-staging` environment because it
requires deployed endpoints and operator secrets.

## Capability states and final manifest

Copy `configs/cloud_release_capabilities.example.json` for the candidate and
set each capability to exactly `enabled` or `not_enabled`. `not_enabled` is a
product/deployment declaration, not a way to waive a failed test. Enabled gates
without matching clean-SHA evidence fail closed.

```bash
make release-evidence \
  EVIDENCE_ROOT=/absolute/path/to/collected-evidence \
  CAPABILITIES=/absolute/path/to/candidate-capabilities.json
```

The output `release-manifest.json` uses three states:

- `PASS`: the enabled capability has matching successful evidence;
- `FAIL`: evidence is missing, failed, dirty, stale or incomplete;
- `NOT_ENABLED`: the candidate explicitly excludes the capability.

External Redis Agent Memory remains `not_enabled` until data export is
explicitly authorized and its live create/search/reconcile/delete test passes.
The production task-execution capability remains enabled only when real gVisor
evidence is present. Skips never become `PASS`.

## Performance evidence

CI records the existing synthetic command-scan workload at 10, 100 and 1,000
sessions with 30 repeats against PostgreSQL. The artifact records query count
and p50/p95/p99 latency. It is a named regression baseline, not a production
capacity claim and currently has no invented universal threshold.

Runtime event projection also emits identity-free summaries for queue wait,
model, tool, client wait and turn latency. Labels are fixed stage names; Session,
Task, User and Memory identifiers are deliberately excluded.
