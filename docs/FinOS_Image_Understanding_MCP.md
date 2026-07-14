# FinOS Image Understanding Through MiniMax

## Purpose

Zebra remains the FinOS Agent. DeepSeek continues to plan, select the daily-log
Skill, combine Core and Journal context, and write the final preview. When a task
contains a broker screenshot, Zebra may call one narrowly registered tool:

`mcp.minimax.understand_image`

The tool sends that one task-local image to MiniMax's official Coding Plan image
endpoint and returns text to Zebra. The returned text is untrusted evidence, not
a Core fact and not an instruction. Zebra must reconcile it with the task prompt,
other materials, and FinOS context before answering.

## Configuration

Image understanding is off by default. Enable it only on the Zebra API or worker
that serves FinOS:

```dotenv
ZEBRA_MINIMAX_VISION_ENABLED=true
ZEBRA_MINIMAX_API_KEY_ENV=MINIMAX_API_KEY
ZEBRA_MINIMAX_API_HOST=https://api.minimaxi.com
MINIMAX_API_KEY=replace-with-a-secret
```

Use `https://api.minimax.io` for the global MiniMax service. The key is read from
the named environment variable and must not be committed.

## Enforced Boundary

- Only `mcp.minimax.understand_image` is registered and preapproved.
- Only an existing JPEG, PNG, or WebP file inside the current Zebra task
  workspace is accepted.
- URLs, data URLs, path escapes, unsupported formats, and images over 20 MB fail
  before provider egress.
- The tool cannot write files, Core facts, Journal entries, or Import Drafts.
- Every execution stays visible in the Zebra trace with proxy target, provider,
  source filename, source SHA-256, and one billable tool-call marker.
- Other MCP tools retain their normal blocked or approval-required behavior.

## FinOS Flow

1. FinOS copies immutable task materials into a temporary, task-specific Zebra
   workspace and includes their relative filenames in the prompt manifest.
2. Zebra calls the MiniMax image tool for each relevant screenshot.
3. MiniMax returns extracted visible facts as text.
4. Zebra applies the selected FinOS Skill and produces a preview grounded in the
   image evidence plus FinOS context.
5. FinOS removes the temporary workspace after the Zebra request returns.
6. Saving the Journal preview and confirming any Core import remain separate
   FinOS user actions.

## Failure Handling

A failed image call produces a failed tool result rather than a fabricated image
description. Zebra may ask for clearer material or report that the screenshot
could not be read. Disable `ZEBRA_MINIMAX_VISION_ENABLED` to roll back immediately
to the prior text-only behavior.
