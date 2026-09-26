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
