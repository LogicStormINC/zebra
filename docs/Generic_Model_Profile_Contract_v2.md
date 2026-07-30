# Generic Model Profile Contract v2

## Status and authority

`MDL-PROFILE-02` is an in-progress, docs-first follow-up to
`MM-NATIVE-QWEN-PHASE1`. Its branch is
`vinson1101/zebra:codex/generic-model-profile-v2`, based on
`codex/qwen-native-multimodal@4533cf4`.

This document replaces model-name capability inference with an explicit model
profile contract. It does not authorize a merge to `main`, a provider switch,
or a FinOS deployment.

## Problem

Phase 1 correctly fails closed, but its composition root currently enables
native image input by comparing the configured model name with one Qwen Flash
identifier. That is a temporary acceptance guard, not the final architecture:

- capability must be selected by a verified profile, not inferred from a model
  name, family, suffix, or regular expression;
- image input is one field of a model profile, not a separate model-routing
  system;
- the OpenAI-compatible adapter must consume resolved capabilities and must not
  contain a Qwen model-name allowlist.

## Minimal contract

The existing provider-neutral `ModelMediaCapabilities` remains the Core
authority for media validation. Phase 2 adds one immutable module-level mapping
at the integration boundary. Its key is `profile_id`, distinct from the provider
model identifier, and its value contains only:

- expected provider identity;
- expected exact model identity;
- the existing `ModelMediaCapabilities` value.

The profile mapping and one pure resolver function are the single source of
truth. A new model becomes usable only after an explicit profile entry and its
contract tests land. Runtime code must not guess capabilities from a model name.
The versioned profile ID carries the runtime revision; verification dates and
evidence remain in docs and tests, not runtime fields.

The selected profile ID comes from generic configuration. Existing provider,
model, endpoint, and API-key references remain configuration values. The
registry never stores endpoint credentials, private endpoint URLs, API keys,
or provider response data.

## Resolution and failure rules

```text
configured profile_id
        |
        v
verified profile registry
        |
        +--> validate configured provider + model identity
        |
        v
OpenAICompatibleModelGateway(profile capabilities)
        |
        v
existing Core preflight + Policy + transport
```

- An absent profile preserves legacy text behavior and is text-only for native
  media. It must not recover the old model-name special case.
- An unknown, provider-mismatched, or model-mismatched profile fails before
  HTTP. Removing the configured profile ID disables native media; no separate
  profile lifecycle state is added.
- A profile declaring image input while the endpoint rejects it produces the
  existing normalized provider failure. Zebra must not silently switch model,
  provider, or MiniMax MCP.
- MCP image fallback remains an independently configured, Policy-bound path.
  Profile selection never grants Tool, network, write, or approval authority.
- DeepSeek's existing role router remains unchanged in this slice.

## Initial verified profiles

The first registry revision records only evidence already established on the
configured Qwen-compatible endpoint:

| Profile | Provider model | Declared input | Tools with media | Streaming with media |
|---|---|---|---|---|
| `qwen-flash-native-v1` | `qwen3.7-flash-2026-07-15` | text + image | yes | yes |
| `qwen-plus-native-v1` | `qwen3.7-plus` | text + image | no until independently verified | no until independently verified |
| `qwen-max-text-v1` | `qwen3.7-max` | text only | n/a | n/a |

The Plus profile may be promoted only by updating its profile revision after
separate tools-with-media and streaming-with-media acceptance. Changing a model
name alone never changes capability.

## Implementation boundary

The smallest coherent change is:

1. reuse `ModelMediaCapabilities` without adding another Core capability type;
2. add one immutable mapping and one pure resolver beside the
   OpenAI-compatible integration;
3. add one optional generic profile ID to `ModelSettings`;
4. have `build_model_gateway()` resolve and validate the selected profile, then
   pass its capabilities to the existing gateway;
5. remove `QWEN_NATIVE_MEDIA_MODEL` and the exact model equality gate.

This slice does not add a Registry service/class hierarchy, provider factory,
automatic router, request-default wrapper, verification/lifecycle state,
capability discovery call, model-family matching, marketplace, database table,
UI, or dynamic fallback state machine.

## Acceptance

- A red regression first proves that native media currently depends on the
  exact Qwen Flash model-name equality.
- A Qwen-looking model name without a selected profile remains text-only.
- An arbitrary fixture model with an explicitly resolved image profile reaches
  the existing serializer, proving capability is not derived from its name.
- Flash accepts its declared image/count/tool/stream combinations; requests
  outside declared limits fail before HTTP.
- Plus accepts image-only requests but fails closed for media plus tools or
  streaming until those combinations are verified.
- Max rejects image input before HTTP.
- Unknown and provider/model-mismatched profiles fail during gateway creation.
- Existing text-only and DeepSeek behavior remains unchanged.
- Focused tests, changed-source Ruff and Mypy, `git diff --check`, and the full
  deterministic suite run; inherited failures are reported separately.

## Delivery route

All implementation and review commits remain on
`vinson1101/zebra:codex/generic-model-profile-v2`. After deterministic and
provider acceptance pass, the maintainer may open a PR from that fork branch to
`hellolukeding/zebra`. No direct upstream feature push or `main` update is part
of this task.
