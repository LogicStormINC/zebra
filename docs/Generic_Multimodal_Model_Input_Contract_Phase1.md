# Generic Multimodal Model Input Contract — Phase 1

## Status and scope

`MM-NATIVE-QWEN-PHASE1` is an in-progress, unmerged implementation slice on
`codex/qwen-native-multimodal`, based on
`c3cc79c3a54f8a0be3a933bbcc43628bf82210ba`. This document is the implementation
contract, not FinOS E2E evidence.

As of 2026-07-30, the authorized preflight has reached HTTP 200 for a text
request and for a request carrying the repository's non-sensitive
`assets/logo.png`. The real smoke fixture is now an inline, deterministic,
non-sensitive 16x16 PNG, which exceeds the provider's greater-than-10-pixel
minimum in both dimensions. With retries disabled, the controlled acceptance
run recorded HTTP 200 for three ordered images, media plus a Zebra typed-tool
definition, streaming media, and an initial/follow-up media replay. A local
Task terminal-follow-up run recorded two image-bearing stream requests (one
for each Task turn); its two additional text-only calls are the independent
best-effort `SessionTitleService`, not media replay or terminal synthesis.
The card remains `In Progress` because repository-wide deterministic and Ruff
baselines remain red on unrelated paths; it is not merge-ready or
FinOS-accepted.

Phase 1 adds provider-neutral image references to model requests. It does not
change durable `SessionMessage.content: str`, create a second payload store,
add OCR or financial behavior, or alter MiniMax MCP.

## Generic model-media contract

Core carries only a `ModelMediaInput` reference with:

- controlled artifact reference;
- declared media type, SHA-256, byte size, display name, stable ordinal, and
  source message identity.

It never carries base64, image bytes, local paths, provider request IDs, API
keys, or provider-private continuation material in a durable Session message,
event, trace, Capsule, Segment, or log.

`ModelGatewayPort` receives `media_inputs=()` as a backwards-compatible request
boundary extension. Existing text providers declare no image input and reject a
non-empty value before transport; they must not silently ignore media.

Each model profile explicitly declares input modalities, image plus typed-tool
support, image plus streaming support, maximum image count, per-image and
aggregate bytes, and a media-token estimator. Core asks the selected provider
for the estimate and includes it in the existing outbound context-window hard
gate; provider-specific token arithmetic stays in the adapter.

## Artifact security and request construction

Only the selected provider adapter resolves a `ModelMediaInput` through the
existing authorized Artifact/Payload Store. It must validate, before any HTTP
request:

1. the artifact reference is present and authorized for its source message;
2. the stored media type, byte size, and SHA-256 match the durable reference;
3. the profile allows the media type, count, per-image size, aggregate size,
   tools-with-media, and streaming-with-media combination;
4. the full text-plus-media request fits the hard token gate.

The adapter builds an OpenAI-compatible `image_url` data URL only in memory,
in ascending ordinal order. Missing, unauthorized, tampered, unsupported, or
oversize media fails closed without compression, text fallback, transport, or
durable byte leakage.

Before serialization, each media reference's source event ID must map to
exactly one internal semantic USER-message declaration. A recovered current
USER message may explicitly carry the Task's exact replay-source event-ID set;
the declaration is not sent to the provider. A missing or ambiguous source
mapping fails closed before resolving bytes or making a transport request.

The authorization root is the current Task/Session's registered attachment
reference. Image ingress stores a second copy in the existing Payload Store
while retaining the existing task-workspace path only for the legacy MiniMax
path. An adapter receives a resolver scoped to those registered refs, never an
unconstrained artifact-store reader; a cross-Task or cross-Session artifact ID
is rejected before bytes are read.

## Replay and recovery

`media_replay_policy=always` applies to the initial request, every tool-result
turn, post-compaction request, tool-disabled terminal synthesis, terminal
follow-up, and recoverable child Segment. Context and Segment data preserve
only the media reference metadata above. A replay path that cannot reconstruct
an authorized matching artifact fails closed rather than omitting it.

Typed tools continue through Zebra Policy, Approval, and Audit. Native media
does not enable Qwen built-in web or code tools, and native mode must not route
the image through `mcp.minimax.understand_image`.

## Qwen Phase 1 profile

The first conforming acceptance profile is `qwen3.7-flash-2026-07-15` with
`thinking=false`, `enable_search=false`, and
`enable_code_interpreter=false`. It reuses
the existing OpenAI-compatible chat-completions adapter, accepts text plus any
positive bounded number of images, supports Zebra typed tools and streaming
only when explicitly declared, and reads the secret only through the
`DASHSCOPE_API_KEY` configuration reference. No secret is hardcoded or emitted.
Other Qwen model names remain text-only unless their selected profile explicitly
passes image capabilities at the provider boundary.

## Acceptance gate

Before this card can be marked Done, deterministic tests must cover:

- single-image serialization and arbitrary-N stable ordering;
- text-only fail-closed rejection;
- media plus typed tools with a replayed next turn and unchanged Policy/Audit;
- compaction and terminal synthesis media replay, plus terminal follow-up when
  the existing child-Segment route is reachable;
- unauthorized, missing, digest-mismatched, per-image/aggregate-oversize, and
  secret/base64/event/trace leakage failures;
- unchanged text-only provider behavior.

Focused Core/provider/context regressions, changed-source Ruff and Mypy, and
`git diff --check` are required. The 2026-07-30 focused run passed 50 tests
with one opt-in smoke skipped. Its five recorded real gateway requests all
returned HTTP 200 with aggregate usage of 819 input, 18 output, and 837 total
tokens; the final local Task probe recorded four more HTTP 200 calls without
recording response content. A clean-config full deterministic run was
`1888 passed, 9 skipped, 9 inherited failures`; full Ruff has seven unrelated
existing errors and Mypy has four documented inherited errors. Provider errors
remain normalized and visible when a declared combination is unsupported; this
Phase 1 profile must not add model-name special cases to hide them. FinOS E2E
remains unrun and unclaimed.

## Owned paths and completion boundary

This slice owns the exact paths listed in `MM-NATIVE-QWEN-PHASE1` in
`docs/AGENT_TASKS.md`. It reuses the current Artifact and Payload Store without
adding a store or schema and does not modify the MiniMax MCP implementation.
Any need to expand beyond those paths stops for Owner approval.
