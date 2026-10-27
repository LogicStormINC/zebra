## Explicit same-Run revision

Use `useZebraSurfaceRevision({config:previousPublicConfig,publicMetadata:previousMetadata,profile})` on a **new committed owner after the old owner stops**. Register using the existing initial Hooks on `revision.surface`, capture once, then explicitly ask the trusted BFF for one durable revision. On unknown, observe only its original receipt. After current mapping confirmation, `revision.adopt(publicConfig,publicMetadata,profile)` returns the real runtime without HTTP; explicitly start it. It requires the exact prior target/Profile, next UI revision and advancing binding metadata, preserves command pending markers, and reuses fail-closed drift/unmount. No automatic remount, authentication, new Run or old Provider upgrade. See [full flow and boundaries](../../../../docs/CA-P3-02Z_react_surface_revision.md).

# 显式初始React Surface（CA-P3-02X）

新增useZebraInitialSurface/useZebraInitialReadable/useZebraInitialAction；capture一次后通过业务BFF原子准入，adopt不发mount、不重领Controller。旧Provider不自动切换。完整交互、StrictMode/unknown/修订边界见[合同](../../../../docs/CA-P3-02X_react_initial_ui.md)。本地准备不是认证或执行证明，不发布npm。

## Readable value commands (explicit opt-in)

With `mode: "bff", surfaceMetadataVersion: 1, clientStateVersion: 1`, `useZebraReadable(name, value)` copies mounted JSON values and updates/removes them with the Hook lifecycle. `useZebraReadableCommand()` returns a one-attempt `submit({action: "run", expectedRevision, idempotencyKey, input: {messages: []}})` function; `resume` requires `input.resume`. Revision is the native command revision, not UI revision. Accepted means durable intent only. A trusted authenticated business BFF compares the public surface and translates using `nativeReadableCommand`; this helper is not an authentication/authorization server. Native credentials remain server-only. Native schema/redaction/digest/command authority stays unchanged. Do not automatically retry CAS/unknown; reconcile the original native idempotency identity at the BFF. Values are not browser-persisted. Old modes remain names/revision only. See [full contract and boundaries](../../../../docs/CA-P3-02G_readable_submit.md).

# @zebra-agent/react

React bindings and host-neutral UI primitives for Zebra Cloud Agent.

## Public component surface

- `AgentChat` composes a Turn timeline, interrupt, resource and sticky composer
  region without owning routing or conversation data. The same controlled
  composer node moves from the centered empty state to the active bottom dock.
- `AgentComposer` provides controlled input, attachment and run controls.
- `AgentConversationTimeline` renders each durable user request as one Turn:
  prompt, public work segments, final answer and artifacts remain together.
- `AgentMessageList` and `AgentActivityGroup` remain available as lower-level
  primitives; work stays open while running, collapses on success, and remains
  open for failed or blocked diagnostics.
- `AgentRunStatus` keeps local submission, server acceptance, queueing, execution,
  user waits, reconciliation, disconnection and terminal outcomes distinct.
- `AgentApproval` and `AgentClarification` render explicit human-in-the-loop
  decisions.
- `AgentArtifacts` and `AgentMemorySettings` expose Host-controlled resources
  without embedding download credentials or memory storage logic.
- `AgentAssetPreview` provides bounded previews for Artifact-backed image,
  video, audio, PDF, Markdown, text, JSON, CSV/TSV and Vega-Lite files. The Host
  supplies Markdown/LaTeX and chart renderers, so framework-specific engines
  and product themes stay outside the base package. Sandboxed HTML is opt-in.

## Composer

Import the component and its explicit stylesheet:

```tsx
import { AgentComposer } from "@zebra-agent/react";
import "@zebra-agent/react/styles.css";
```

`AgentComposer` is controlled. The Host owns message state, attachments,
capability/model/reasoning choices and every execution action. The component
does not call Zebra APIs, store credentials, or create a second Agent runtime.

The default theme is scoped under `.zebra-agent-composer` and
`.zebra-agent-chat`. Use the typed `themeTokens` prop for per-instance branding:

```tsx
<AgentChat
  composer={composer}
  theme="dark"
  themeTokens={{
    accent: "#66ccff",
    input: "#111827",
    composerRadius: "18px",
    contentWidth: "880px",
    fontFamily: "Inter, system-ui, sans-serif",
  }}
  turns={turns}
/>
```

`AgentComposer` accepts the same prop when used by itself. Every token value is
a CSS value string. Unspecified tokens keep the package defaults, so changing a
brand color does not silently alter the ZCode-style layout.

| Group | Tokens |
| --- | --- |
| Color | `surface`, `surfaceRaised`, `input`, `text`, `muted`, `faint`, `border`, `hover`, `accent`, `accentText` |
| Geometry | `draftWidth`, `contentWidth`, `wideContentWidth`, `composerRadius`, `userBubbleRadius` |
| Typography | `fontFamily` |

Hosts that theme through stylesheets may set the equivalent
`--zebra-agent-*` CSS custom properties on either root instead. Labels remain
replaceable through `labels`, so product copy and localization stay outside the
reusable package.

## Turn timeline

Pass `AgentChat.turns` when the Host can project its durable session events into
`AgentConversationTurn[]`. Use a stable `scrollKey` per conversation so the
surface restores that conversation's reading position. Legacy `messages` and
`activities` remain supported for incremental adoption, but a Host should not
pass both representations for the same work.

The package renders public analysis summaries and tool status only. Private
reasoning, raw tool payloads and credentials do not belong in the Turn contract.

## Lifecycle and recovery

Pass an `AgentRunStatusProps` object to `AgentChat.runStatus`, or render
`AgentRunStatus` directly. `reconnect`, `resume` and `retry` are separate Host
callbacks. The component suppresses replay while a write is being reconciled,
and only accepts a Host-approved `safeMessage` plus an opaque `diagnosticId`—it
has no raw-error or private-reasoning field. A terminal run overrides stale
running activity state so the completed work log can collapse normally.

## Runtime boundary

Use `ZebraAgentProvider` and the exported hooks for Agent runtime integration.
Use `ZebraHitlProvider` for approval and clarification surfaces. A Host should
adapt its domain state into these contracts rather than import package source
files or duplicate runtime ownership.


## Same-origin BFF browser mode

Prefer `mode: "bff"` for embedded business UIs. The business BFF keeps native HostGrants,
Session credentials and Controller fences; the browser gets public metadata only:

```tsx
const config = {
  mode: "bff" as const,
  baseUrl: "/api/agent/surfaces/public-binding-id",
  clientSessionId: bootstrap.clientSessionId,
  controller: bootstrap.controller,
  taskId: bootstrap.taskId,
  runId: bootstrap.runId,
  runBindingId: bootstrap.runBindingId,
  clientBindingDigest: bootstrap.clientBindingDigest,
  actionContractDigests: bootstrap.actionContractDigests,
  initialUiRevision: bootstrap.uiRevision,
};
// Pass config to ZebraAgentProvider and register actions with useZebraAction.
```

`bootstrap` above means the product BFF's sanitized native-admission response, not Overdoze's
identity-only bootstrap. No extra Agent identity token is created. Existing business login/Cookie,
current Agent identity, Origin/CSRF, durable surface mapping and native authorization stay server-owned.
Public IDs and `controller` are hints; the BFF independently checks and rejects foreign scope/role.
Never serialize `sessionCredential` or `controllerFenceToken` into this mode, or fabricate a value
for the legacy validator. BFF v1 supports bounded polling, not an undocumented SSE proxy.

`useZebraClientStatus()` observes `connecting`, `ready`, `unavailable`, or `stopped`.
Ready follows mount/poll success; it does not prove native admission or task completion.
Old callers that exhaustively type the former three-state union must handle `unavailable`.
The existing native admission response does not directly return an action-digest map; production
BFF integration still needs public native digest facts and mount/RunBinding/fence synchronization.
`useZebraReadable` currently registers names and revisions only: no value-upload/Context proof.
Local storage restrictions limit refresh deduplication; an already running JavaScript handler cannot
be rolled back. Unknown business writes require their own operation/result reconciliation.

The original config and legacy SSE remain available. This source addition is not an npm release,
a production BFF, or real business IdP/Runtime/Worker end-to-end acceptance.

## Synchronized native surfaces

BFF integration with client-surface-metadata/1 opts in using `surfaceMetadataVersion: 1` and the actual admitted `initialUiRevision`. Provide the native binding/action digest facts; the trusted BFF retains all native credentials and returns only `publicClientSurfaceMetadata(nativeResponse)` after persisting its new fence. The runtime pauses dispatch, drains old work, validates the public response and updates binding coordinates. Unknown outcomes stop without automatic remount/release. Persisted unresolved work requires trusted reconciliation. See [protocol and evidence boundaries](../../../../docs/CA-P3-02E_sdk_surface_sync.md). Legacy/unnegotiated mode remains compatible and does not consume remount metadata.

## Explicit command recovery1

Enable `commandRecoveryVersion: 1` with BFF Readable1 and synchronized surface1. Use canonical lowercase UUID keys and working per-tab Storage. `useZebraReadableCommandRecovery()` returns a nullable `{pending(), reconcile(key)}` view. Pending reloads stay stopped before Provider lifecycle work. Query only; unknown never permits resubmit. Accepted clears only the original key; fetch a fresh trusted bootstrap and replace the Runtime/Provider before mounting again. Markers store keys only, not messages/values/credentials; cleared storage and another device need business-side discovery. BFF uses its own durable journal and the published native original-Segment receipt/precondition contracts. No npm publication or production IdP/HA guarantee.
