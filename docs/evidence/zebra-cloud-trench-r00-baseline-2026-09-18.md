# Zebra Cloud / Trench R00 baseline

- Date: 2026-09-18 (Asia/Shanghai)
- Plan: `/Users/lukeding/Downloads/zebra_cloud_trench_systematic_remediation_plan_v1.0.md`
- Zebra branch: `cloud-agent-trench`
- Zebra baseline commit from the plan: `07dca87304dc8cf01a56a00245751ea8997e38f5`
- Zebra current commit: `026f59efe5f67062f0495951564e71fe2549c3ac`
- Current commit delta: the current branch contains the previously requested
  GPLv3-or-later license commit on top of the plan baseline.

## Repository state

Zebra's worktree was clean when this baseline was collected. The Trench
checkout at `/Users/lukeding/Desktop/playground/2026/product/Trench` is at
`05c6bc106cb993f21d68a929ea7589871e4aa568` (`feat(toc): connect dashboard
live market feeds`) and contains extensive pre-existing modified and
untracked work across backend, workers, migrations, tests, and the dashboard.
That worktree is intentionally preserved and is not an R00 input to modify.

The task registry did not previously contain the R00-R14 plan task IDs. R00 is
registered as `CLOUD-REMEDIATION-R00` in this commit so later implementation
slices have an explicit dependency and owned-path boundary.

## Zebra validation baseline

Commands were run from the Zebra repository at the current commit:

| Check | Result | Classification |
|---|---|---|
| `scripts/check_file_sizes.py` | passed; 2,204 files checked, 0 violations | baseline green |
| `ruff check .` | failed with one `I001` in `apps/api/src/zebra_agent_api/host_auth.py:3` | pre-existing baseline failure; outside R00 owned paths |
| `uv run pytest --collect-only -q` | passed; 5,336 tests collected | collection green |
| Mypy / eval | not run by `make check` | blocked by the Ruff failure in the current gate sequence |

`make check` therefore does not pass at the baseline. R00 records this failure
without applying the suggested import-only fix; the fix must be assigned to a
later owned implementation slice rather than hidden in the evidence task.

## Production runtime fingerprint

Read-only inspection used the `ubuntu` account on `192.168.110.30`; no secret
values were recorded.

- Host: `ubuntu-GL65-Leopard-10SER`
- Compose project: `trench-legacy`
- Compose files:
  `/opt/trench-build/docker/compose.prod.yml`,
  `/opt/trench-build/docker/compose.zebra-override.yml`
- PostgreSQL: `16.11`
- Alembic version: `3c4d5e6f7081`
- API container: `/trench-api`, image `trench-backend:local`, digest
  `sha256:d80722b98e379835934986c18776f86bf328465d8209a8f423212b4e41c7062b`
- Frontend container: `/trench-frontend`, image `trench-frontend:local`,
  digest
  `sha256:b98046b91c5408f047be5cf19896d7f258297f75a98f7c545f4b259bc1a8bcd2`
- PostgreSQL image digest:
  `sha256:31482568...` (recorded in the operator inspection output)
- Redis image digest:
  `sha256:eca6112...` (recorded in the operator inspection output)

Configuration fingerprints, recorded instead of contents:

| File | SHA-256 |
|---|---|
| `/opt/trench-build/env.deploy` | `0638a6dceb4fd8299148a6e04298de2285f455479075d9224dcf723448522c4d` |
| `compose.prod.yml` | `6ba66a6d44d388115113641a4b0abd80aee32accd33a43089d305595de182f29` |
| `compose.zebra-override.yml` | `d941f5b0a45bec67519b364c171f3023a5fd92eeb06b2e77ae326953cece76a5` |

The earlier dashboard observation also recorded a server-side Polymarket
upstream timeout while the local hot/news feeds were available. This is a
runtime observation for a later cross-repo acceptance slice, not proof of a
Zebra core defect.

## G0 decision

R00 baseline collection is complete and the evidence boundary is now explicit.
G0 is **not yet closed** until this registry entry, this evidence document,
`PROGRESS.md`, and `WORKLOG.md` are committed together. The next allowed work
is a separately claimed R01/R02 slice with its own owned paths and regression
tests. No production deployment or cross-repo acceptance is claimed by R00.
