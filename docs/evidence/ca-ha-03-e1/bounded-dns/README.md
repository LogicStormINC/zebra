# CA-HA-03 bounded DNS follow-up

Ordinary guarded requests reused the auxiliary no-thread loop. Hostname DNS was
refused after the durable model reservation. Keep the original failed Task and
NULL receipt; this change is not authorization to resend or refund it.

Only ordinary guarded I/O uses a new loop. The resolver is a stdlib subprocess
with bounded input/output, stripped environment, Linux parent-death fence and
CPU/address-space limits. Cancellation kills and waits for the exact child,
including cancellation during spawn or repeated cancellation during reap.
Numeric endpoints use AI_NUMERICHOST/AI_NUMERICSERV. Auxiliary behavior, original
model URL/SNI/CA checks, wire bytes, budgets and retry policy stay intact.
A one-second cleanup bound reports unconfirmed exit as an error, never success.

Validation: 74 focused tests including actual child resolution/error/kill/reap,
repeated cancellation and guarded localhost certificate-verified TLS/settlement.
The independent AI review also ran 74 tests and reported no Critical/Important;
this is not human review. `make check` exited zero.

Both existing staging engines ran separate, temporary nonroot, network-none,
read-only containers with no credentials or database calls. The exact candidate
DNS module resolved the test hostname through owned /etc/hosts and killed/reaped
a hanging resolver. Production and existing application containers were untouched.
These checks cover DNS plumbing, not a successful end-to-end model Task.

Next: freeze source; build and hash both native images including the new module;
create a real multiarch manifest and fresh frozen publication approval; retain
three old Tasks and the unknown reservation through a cold staging promotion;
submit one new synthetic case, never replay an old Task. Full E1 load/fault/soak
and later HA gates remain pending. CA-HA-04 remains locked.
