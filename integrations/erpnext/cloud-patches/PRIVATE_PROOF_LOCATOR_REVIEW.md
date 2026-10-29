# Proof locator source narrowing — isolated candidate

Only two application/test files differ from the reviewed `outputs/zebra-erpnext/cloud-patches` source. No original source, server, database, configuration, service, container or Git state was modified. This is a prerequisite source candidate; no SQL view/role implementation or compiled image is included.

`private_facts(..., *, metadata_only=False)` preserves the default full native getter, its missing-row refusal and its original complete third result. The proof-only branch selects exactly `workspace_root` from `workspace_projections` by namespace/session and returns `None` as result three. It does not create a partial projection. The existing UUID/canonical locator, active Task/segment, native binding/lineage, private generation/source, principal/Run, scope/quota/state/volume and identity-hash checks remain shared after that branch. The ponytail comment marks that external allocation proof intentionally omits full projection validation; Worker containment retains it.

Only `native_workspace_proof` opts in. The complete caller trace in the reviewed override tree is:

- `erp_private_workspace.native_workspace_proof`: explicit `metadata_only=True`.
- `erp_workspace_policy.ERPWorkspaceContainment.require_in_transaction`: unchanged default. Its `workspace != native` recovery comparison still receives the complete native projection.
- `erp_private_preparation.prepare_private_command`: unchanged default, although it ignores result three.
- Existing native regression calls: unchanged defaults plus new opt-in cases.

Trace command: `rg -n 'private_facts\(' outputs/zebra-erpnext/cloud-patches`. No other production caller was found. Earlier source review found no root-only existing native getter, so the stdlib/native SQL branch is the smallest coherent change. No new dependency or production abstraction was added.

The existing `check_private_workspace_native.py` is extended with actual native full-getter reconstruction parity, exact default third-result equality, containment rejection when only definition_snapshot/snapshot_path changes, exact metadata SQL/parameters, full getter and definition-model read traps, missing workspace/Task and malformed/noncanonical/wrong-UUID refusal, quota/state/owner/source refusal, identity/instance parity and AST guards for the sole opt-in/default callers. Existing private authority and resolver checks remain runnable in the same file.

## Validation boundary

A local offline smoke passed with the captured105 packages placed before existing repository fallback packages; this is useful syntax/fixture evidence only, because the fallback may differ from pinned105. That mixed local runner was removed. It is not exact native-image acceptance.

`create_packet.py` emits the frozen `check_packet.py`. Root can run the packet through stdin with native c3 image Python, network none, read-only root filesystem, uid65532, dropped capabilities, no-new-privileges and bounded resources. It checks the installed baseline module SHA256 before replacing that one module in memory and runs the extended native check. The unchanged preparation source is embedded solely for its AST default-caller check. Imports/fixture checks are real native dependencies; database/Host/provisioning seams are mocks, and no model or business call occurs. A passing packet demonstrates source-overlay regression behavior on c3 dependencies; it does not demonstrate a newly compiled candidate image, PostgreSQL ACL/view enforcement or production acceptance.

A new immutable Worker image is required because this module is compiled/copied into the application image. Also rebuild API if its shared COPY includes this override. Pin the root helper to the new image and repeat exact-image proof/confinement and disposable native105 role/view QA before activation. Existing c3 cannot be called the compiled executable identity of this changed source; a host-only patch is insufficient. Worker/API/default preparation and containment caller source is untouched, and no production activation is authorized by this candidate.

Next independent slice: nine control views with workspace `(deployment_namespace, session_id, workspace_root)` and the eight other reviewed allowlists, namespace-wide only under root's trusted-native-produced CONTROL boundary, no body/definition_snapshot and no helper base grants. Typed extra-forbid binding metadata remains the existing native validation contract; no binding rewriting or new abstraction is introduced here.

`SHA256.json` freezes the two original inputs, unchanged caller inputs, candidate source/test, packet/generator and unified diff. The root should add the exact c3 packet execution result and immutable image identity as separate evidence.
