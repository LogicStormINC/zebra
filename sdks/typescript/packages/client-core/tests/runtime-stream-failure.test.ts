import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";

test("actual runtime contains permanent stream failure and preserves accepted cursor", () => {
  for (const poison of ['invalid JSON', JSON.stringify({ type: "STATE_DELTA", delta: {} })]) {
    const source = `
      import assert from "node:assert/strict";
      import { ZebraClientRuntime } from ${JSON.stringify(new URL("../src/index.ts", import.meta.url).href)};
      const data = new Map(); let requests = 0, observed = 0;
      const runtime = ZebraClientRuntime.fromConfig({
        baseUrl: "https://fixture.test", clientSessionId: "11111111-1111-4111-8111-111111111111",
        sessionCredential: "11111111-1111-4111-8111-111111111111:session-secret-value",
        streamUrl: "https://fixture.test/stream", streamVersion: 2,
        storage: { getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value) },
        fetchImpl: async () => { requests++; return new Response('id: accepted\\ndata: {"type":"CUSTOM","name":"business","value":1}\\n\\n' + 'id: poison\\ndata: ' + ${JSON.stringify(poison)} + '\\n\\n'); },
        onObservation: async () => { observed++; },
      });
      await runtime.start();
      await new Promise(resolve => setTimeout(resolve, 30));
      assert.equal(runtime.getStatus(), "unavailable");
      assert.equal(runtime.isStopped, true);
      await runtime.start(); await runtime.poll();
      assert.equal(requests, 1);
      assert.equal(observed, 1);
      assert.equal(JSON.parse([...data.values()][0]).lastEventId, "accepted");
      runtime.disconnect();
    `;
    const child = spawnSync(process.execPath, ["--import", import.meta.resolve("tsx"), "--input-type=module", "-e", source], { encoding: "utf8", timeout: 5000 });
    assert.equal(child.status, 0, child.stderr || child.error?.message);
  }
});
