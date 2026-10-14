# Recorded v2 stream latency example

From `sdks/typescript`, using Node 22.18–24:

```sh
pnpm build
node examples/stream-latency/run.mjs
```

Open the printed localhost URL and click **Replay stream**. The real exported
ZebraClientRuntime parses recorded SSE frames, ConversationStreamReducer updates
messages and AgentMessageList displays a labeled draft before **Commit final**.
The page measures first observation, first body DOM commit and unchanged historical
content render counts. **Commit final** replaces that same message and removes
the draft label. No credentials, backend, model or Trench dependency is used.

The runner reuses esbuild already installed with tsx. It bundles built package
exports, with no imports from package source or new dependency. This example
measures browser work after synthetic frame production, not end-to-end model TTFT.
