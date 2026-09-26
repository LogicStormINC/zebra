# @zebra-agent/react

React bindings and host-neutral UI primitives for Zebra Cloud Agent.

## Public component surface

- `AgentChat` composes the message, activity, interrupt, artifact and composer
  regions without owning routing or conversation data.
- `AgentComposer` provides controlled input, attachment and run controls.
- `AgentMessageList` and `AgentActivityGroup` render public conversation state;
  the activity group stays open while running and can collapse after completion.
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
`.zebra-agent-chat`. Override the
`--zebra-agent-*` CSS variables on that element to integrate it with a Host.
Labels are replaceable through `labels`, so product copy and localization stay
outside the reusable package.

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
