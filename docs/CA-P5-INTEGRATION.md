# CA-P5-INTEGRATE: authorized P5 mainline integration

The user authorized merge/push and merged-ref cleanup in both repositories. Native
product mainline is `cloud-agent`, not the obsolete GitHub default `main`.
The integration parents are remote ac8473b3 and verified P5 f8356c30. All P5 source
commits, including fixed producer9e91d75f, remain reachable and immutable. No deployment
or production migration is authorized or executed.

## Merge resolutions and compatibility

Worker construction and loop retain **both** current safety-net recovery/dead-letter
logic and P5 Runtime gates/graceful drain. Cancellation retains current AG-UI preparation
and immutable P5 admitted-event identity verification; fresh caller authority is unchanged.
Config profile validation is relocated to the existing runtime_settings module to
avoid adding a file-size violation; settings imports preserve the prior helper name.
The current safety connection gets a missing return annotation. Governance histories
from both parents are retained. Two merged tests now identify their named migration
and account for default-disabled Host authority in the baseline contract; no protocol
or security assertion is removed.

### Published migration version collision

Both parents published different immutable 115/116 migrations. Keep original SQL,
checksums, ledger versions and applied timestamps; do not rewrite existing rows.
The canonical new catalog is ordered 115 AG-UI routing / 116 standard cells /
117 safety overrides / 118 Runtime gate / 119 original gate termination.
For a ledger with the **exact published P5 115 name and checksum**, the physical
history plan retains gate115/termination116 and allocates AG-UI118/cells119; safety117
and every other identity stay fixed. Mixed identities, unknown versions and altered
checksums still fail closed. Startup, Worker capability and command-cutover schema gates use the exact same
plan. The existing runner.MIGRATIONS injection seam is preserved so historical-prefix
upgrade proofs remain valid. Catalog objects and immutable source commit9e91d75f are
not mutated. Only an explicitly invoked migration command can add missing schema;
this integration invokes it only inside disposable test PostgreSQL schemas.

Real SQL acceptance covers canonical AG-UI117 and original P5 histories, concurrent
repeatable migration, startup/Worker schema gates, original ledger/applied_at bytes,
original gate intent/unknown receipt retention, and corrupted-checksum rejection.
Historical Bundle109 and Coverage fixtures are also exercised on actual PostgreSQL;
all70 focused SQL cases pass, including the command-cutover gate without granting cutover.

## Final merged-tree verification

Fresh make test: **11618 passed,3155 skipped,15 failed** (1397.82s). All15 exact
failed node IDs also fail on the clean remote ac8473b3 baseline (2.70s); no new
failing cases. They include Coverage HTTP/strict recovery, AG-UI stream and SDK
snapshot, configuration-baseline fixtures and the inherited repository-size gate.
No failure is hidden or relabelled as green. Full make check remains red on the
16 inherited size violations; independently executed Ruff reports4924 inherited
ERP errors. Mypy1492, Eval30, product-boundary and both progress repair/risk checks
pass. Go make test30 packages and make check pass (74 inherited nonblocking warnings).
3,429 source/contract fingerprints remain unchanged through the final serial run.
[Structured validation](evidence/ca-p5-integration/validation.json) keeps exact cases
and non-pass interrupted attempts distinct. Frozen V31 is not rerun or relabelled.

## Verification and branch preservation

- Verified P5 full-suite/V31 evidence stays in docs/CA-P5-08_exit_verification.md;
  merged-tree checks are recorded separately in validation.json, not relabelled V31.
- [Inherited check failures](evidence/ca-p5-integration/inherited-checks.json): all
  16 file-size violations and all4924 Ruff errors have identical blobs to the remote
  ac8473b3 baseline; Ruff errors are entirely within integrations/erpnext. No gate
  exclusion or limit is weakened. make check therefore remains red on that baseline.
- [Original branch tips](evidence/ca-p5-integration/branches-before.json): local
  unpublished97463d00 is retained under codex/preserve-local-cloud-agent-97463d00;
  it is not silently pushed as P5. Dirty/unmerged unrelated worktrees/refs remain.
- Verify published cloud-agent before deleting ancestor-only topic refs with old-tip
  guards. Clean occupied topic trees may detach at the identical commit; never remove
  directories, caches, history, original receipts, volumes or user data.
- Overdoze main908160e has already been pushed;24 local/22 origin merged topics removed,
  original pnpm-lock SHA256 fe5e9a7f35e9f817aa4f3803e24ccd05d2527e0d95c9b288dfde4ff918f656c0 retained.

Final push/cleanup outcomes are verified by the delivery receipt, not anticipated by
this document. Remote changes are normally merged, never force-rewritten.
