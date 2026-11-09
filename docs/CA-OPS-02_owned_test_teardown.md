# CA-OPS-02 — Owned temporary test teardown

The CA-P5-06 full gate left23 anonymous image volumes while containers and
networks were removed. Five shared PostgreSQL generators and one conformance
shell use force-only Docker removal. Module-scoped fixture imports reuse these
generators in other test modules, so fixing each generator covers its callers.

Reuse the existing teardown regression from the test-anonymous-volume-cleanup
worktree; no new abstraction or dependency. Six argv now include anonymous-volume
removal. Targets remain the exact IDs/names produced by each fixture. Named
volumes are not removed by container teardown. No production code is changed.

The regression first failed6 static cases (3 passed,12 live opt-in skips). After
the six one-line fixes,21 checks passed, including normal/exceptional exits,
actual Docker anonymous-volume absence, named sentinel content retention and
rejection of hardcoded business names/wildcards/command substitution. Newly
created sentinel resources are removed only by their exact owned identifiers.
The live matrix left container, volume and network identity sets unchanged.

The historical23 anonymous volumes lack complete surviving mount ownership
events (daemon history is limited). They are recorded and preserved, not pruned
on temporal correlation alone. New gate runs inventory before/after against this
baseline; no task/history/receipt/unknown/Coverage data is removed.

Full Native make test passed11225/3080 conditional skips in1305.68s; resource
identity sets exactly match baseline. make check passed1447 typed sources/30eval; Overdoze25de8c9 remains unchanged
with its already verified30 race packages/selfcheck and check. No S1 rebuild,
production operations, main merge or broad cleanup is part of this task.
