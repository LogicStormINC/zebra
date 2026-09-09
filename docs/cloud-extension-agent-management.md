# Agent-native extension management

Status: source in review; local Worker/Host deployment and backend Agent acceptance
verified on 2026-09-09. GitHub import added below. Browser acceptance is separate.

Installed Skill management now displays publication `name`, `description` and
`version_label`, resolved by exact signed-user scope and installed version.
Reads never fetch archives or run Skill content. Missing legacy metadata leaves
the installation manageable with explicit UI fallback; mismatched digests are
not described using another version. Concurrent metadata reads are capped at
eight per bounded list page. Trench renders descriptions as plain text, offers
name/purpose search over loaded pages, expandable details and revision-checked
enable switches. Actual existing better-writing installation verified in Chrome;
no reinstall or migration needed. No model-generated capabilities or translated
claims are invented when metadata is absent.

Capability rollout includes existing conversations: Trench `trench-native-v12`
supersedes pre-import v11 bindings through the existing scoped CAS successor
path, preserving the frontend conversation/history. Otherwise a pre-deployment
pending clarification can resume an exhausted final-only model budget and
repeat stale capability claims even on an updated Worker. Do not reset frozen
Turn counters/authority. Acceptance must include an old suspended conversation,
not only fresh accounts (`github_skill_live.py --legacy-clarification`).

Reuse PostgreSQL configuration revisions, published Skill packages, catalog
refresh, Worker execution authority and the existing tool/effect pipeline.
No second database, new queue, arbitrary HTTP client, or secret model input.

Implementation order:
1. Typed bounded management tools over existing scoped application services.
2. Worker composition checks live Task/Turn, lease and explicit signed
   extensions.read/manage scopes. Ordinary agent.run never grants management.
3. Reuse protected MCP refresh; no synthetic VerifiedHostGrant.
4. Host/Broker integration, then real Agent and browser acceptance.

Tools list current installations/connections, create disabled MCP connections,
install published Skill versions, enable/disable, and refresh MCP catalogs.
Endpoint updates disable the connection and clear its old credential reference.
Skill upgrades require a same-scope ready version of the same Skill.
Updates and upgrades remain revision-guarded. File publication/upload is
separate from installation; the GitHub import tool orchestrates both, with
fixed public GitHub endpoints only and no host script execution.

New configuration is available to future Turns subject to Task capability
ceilings; it never changes the running Turn snapshot. Disabling can revoke a
current operation. A saved connection without an eligible current catalog is
not reported as usable. Refresh after enabling because config revision changes.
Credential-required connections remain pending and tell users to complete
authentication in extension settings; secrets must never be pasted to chat.

Checks: scope mismatch, permission expiry, malicious extra arguments, idempotent
create, revision conflict, pending authentication, bounded listing and safe
error output; then Worker registration and ordinary-chat regression.

## Implemented tools

- extensions.list
- extensions.add_mcp
- extensions.install_skill
- extensions.import_skill
- extensions.set_enabled
- extensions.refresh_mcp
- extensions.update_mcp
- extensions.update_skill

Worker registers only names permitted by frozen signed Host scopes. Each call
revalidates current Task identity, execution authority and lease. Mutations
revalidate again immediately before persistence after intermediate reads.
Writes remain in the existing fenced effect pipeline, not a second task queue.
Network-disabled Tasks do not receive refresh or GitHub import. Refresh reuses the
HTTP service implementation with repeated authorization checks; Worker never
synthesizes a VerifiedHostGrant.

## Remaining integration gates

- Trench ordinary grants now include extensions.read/manage from the same
  Host-owned ceiling exposed in authenticated viewer responses. Broker validates
  the ceiling from the viewer or signed workload principal, as well as its
  operator allowlist. Roll out both services before enabling the new Worker.
- Existing Task Skill ceilings remain immutable. Trench now discovers enabled
  scoped installations before new user Turns and includes their IDs at creation.
  Capability-set changes create an idempotent successor, retaining frontend
  conversation and existing Host conversation context. Same-ID upgrades reuse
  the Task and get a fresh version snapshot on the next Turn.
- The low-level install tool requires a published version. GitHub links now use
  extensions.import_skill to download, validate, publish, install and enable.
  Arbitrary URLs, Git clone, repository script execution and private GitHub
  credentials are not supported by this bounded public importer.
- Secure credential-entry UI remains separate. Pending-auth connections are not
  usable merely because they were saved or enabled.
- Real Agent Skill import/upgrade/read and settings API readback have passed;
  installation/Turn cross-user HTTP rejection is covered by automatic binding
  acceptance. Full browser and process-restart acceptance remain separate.

Historical initial validation: 119 focused tests passed; full suite 4295 passed / 875 skipped;
make check passed (size, Ruff, Mypy 910 sources, Eval 10/10).

## Login-once delegation (confirmed 2026-09-09)

No new consent database, browser secret, perpetual Grant or per-Turn prompt.
Trench's existing authenticated single-user workspace grants access to its
subscription/history/assets and extension configuration capabilities. The
viewer descriptor is informational; the Broker only trusts the descriptor
obtained from Trench, never browser-supplied scope lists. Existing sessions
receive current capabilities on their next authenticated viewer request.
Future workspace roles must reduce this single Host-owned ceiling centrally.

The Broker intersects requested scopes with the Host ceiling and operator
allowlist. Legacy Hosts missing a ceiling retain base compatibility but cannot
mint extensions.*. Scope declarations in workload requests are inside the HMAC.
Before signing a workload request, Trench rechecks active account and workspace
ownership. Browser-cookie exchange continues to validate session revocation.

Accepted durable tasks intentionally outlive browser logout, as before this
change; logout blocks new browser actions, not already accepted work. Account
disable/workspace changes block further workload exchanges. Already issued
grants remain usable until their existing expiry unless execution is cancelled
or existing runtime authority is revoked; this is not immediate global logout
revocation. Third-party OAuth/credentials still require the provider's own setup.

Task generation and idempotency namespace advance together so older frozen
Host ceilings do not silently reuse Tasks without extension authority. Running
Turns retain their snapshots. Read/reconnect/cancel use the persisted active
Task binding rather than rediscovering configuration. Successor idempotency
includes its predecessor, preventing an A-to-B-to-A configuration cycle from
reviving stale Tasks. Compare-and-swap prevents a late admission overwriting a
newer binding. No new table or migration is needed.

Cloud task admission verifies explicit Skill IDs against enabled installations
and ready publications in the authenticated scope. Canonical published UUIDs
and existing local component names share the same validation. Only a recovered
CloudSkillCatalog adds skills.list/read to research; local research stays as-is.
Installation updates keep snapshots immutable, but existing live reauthorization
can deny subsequent reads against a changed/disabled installation (no promise
that every in-flight read continues after revocation).

### Automatic binding acceptance and operating boundary (2026-09-09)

Trench scans at most four 100-record pages, matching Cloud selection, and fails
closed rather than partially loading excess/invalid catalogs. At most 32 enabled
Skill IDs are selected. Same-ID version upgrades are resolved by the next Turn's
snapshot. Add/remove/re-enable uses a predecessor-qualified successor Task with
CAS; frontend conversation identity remains unchanged. Successors receive an
bounded quoted Host context in their initial prompt (up to 4,000 context
characters plus 12,000 recent-history characters). This is not full event-store
copying and does not grant cross-Task history access.

Do not add arbitrary history_session_ids as a shortcut: referenced-session
principal/workspace authorization and default-deny behavior need a separate
review before broader cross-Task history is enabled.

Trench uses ZEBRA_STREAM_IDLE_TIMEOUT_MS (default 60000, allowed 1000–300000)
independently of the existing five-second control HTTP timeout. Public output
still streams immediately; the separate budget does not buffer content or
disable eventual idle termination.

The opt-in Trench script tests/api/skill_binding_live.py creates labelled
isolated accounts and real Skill publications. Passing HTTP→Trench→Broker→API→
Worker→model run conv_skill_acceptance_d5b35f4efb8e4a9d verifies initial reply,
publication/install/enable, first Skill read, Agent-native upgrade, new-version
read, disable/successor and another user's installation/Turn 404. The returned
markers are only in the Skill files, never supplied in the user prompt.
This is real backend end-to-end evidence, not a browser UI acceptance claim.

Development network caveat: the local proxy resolves api.deepseek.com to a
198.18.x.x fake IP and TLS fails. Worker currently uses the temporary Compose
overlay /tmp/zebra-skill-acceptance-network.yml with the public address returned
by HTTPS DNS during acceptance (3.173.21.63). Domain/SNI/certificate checks remain
intact. This address can change: fix the proxy's per-domain DNS/routing and then
recreate Worker without this overlay; do not promote this mapping to production
or change model base_url to an IP. No system proxy configuration was changed.

### Public GitHub Skill import (2026-09-09)

`extensions.import_skill(url, path?)` is a governed write tool with explicit
Host extensions.manage and network eligibility, not an unrestricted fetch tool.
It accepts public github.com repository URLs or tree/ref URLs. Root SKILL.md
wins; otherwise a single regular nested Skill is selected, and ambiguity returns
candidate paths for the user to choose. Branch names containing slashes need
an encoded ref segment. References are retained; repository license is copied
into references/repository-LICENSE. Symlink aliases are not followed; no files
are extracted to disk and no downloaded scripts are executed.

Public GitHub API resolves a commit, then codeload downloads by SHA. When the
API is rate-limited, the bounded official codeload ref archive supplies the Git
commit comment; a second SHA-addressed archive must match it. DNS must resolve
public addresses; TLS/SNI checks remain on, redirects and credentials are refused.
Download limit is 10 MiB, expanded total 50 MiB, at most 1000 archive entries;
the existing Skill package validator applies before any publication writes.

Publication reuses the user-scoped durable store and object store. Task/Turn
authority is rechecked before network steps, reservation, object upload, ready
transition, installation and enable. Repeated imports reuse an existing Skill
installation; changes use revision-checked upgrade. Concurrent replay returning
a different version fails rather than claiming the requested version installed.
New capabilities apply to the next user Turn using automatic binding above.

Real sample: https://github.com/forjd/better-writing at
dd9d0a50581a7652fb38f03b7b751741ed917993. Validated package: 40219 bytes, nine files.
Trench tests/api/github_skill_live.py uses an isolated account, sends the URL
to the real Agent, checks enabled persisted installation, reads
references/voice-and-context.md next Turn, and verifies no duplicate on reimport.
First passing conversation: conv_github_skill_12501c669e3542f5; 12.20s import,
8.14s reference read, 8.11s reimport request. Durable events confirm actual
extensions.import_skill and skills.read execution (not merely model claims).

Development proxy caveat also applies to GitHub. The temporary Worker overlay
currently maps api.github.com and codeload.github.com to public DNS results
20.27.177.116 and 20.27.177.114. These acceptance-only addresses can change;
repair per-domain DNS/routing before removing the overlay or production use.
No system proxy or user credentials were modified. No Git push in this slice.
