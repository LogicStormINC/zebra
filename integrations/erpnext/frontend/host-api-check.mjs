// Execute the relocated real Host adapter: same-origin, CSRF, native session/fence and no retry.
import assert from 'node:assert/strict';
import * as esbuild from 'esbuild';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const owned = mkdtempSync(join(tmpdir(), 'erp-host-gate-'));
try {
  const output = await esbuild.build({
    entryPoints: [new URL('./host-api.ts', import.meta.url).pathname],
    bundle: true, format: 'esm', platform: 'node', write: false,
    plugins: [{ name: 'capture-native-client', setup(builder) {
      builder.onResolve({ filter: /^@zebra-agent\/client-core$/ }, () => ({ path: 'client', namespace: 'fixture' }));
      builder.onLoad({ filter: /.*/, namespace: 'fixture' }, () => ({
        contents: 'export class ZebraClientRuntime { static fromConfig(config) { globalThis.nativeConfig = config; return globalThis.nativeClient; } }',
      }));
    } }],
  });
  const entry = join(owned, 'host.mjs');
  writeFileSync(entry, output.outputFiles[0].text);
  globalThis.location = { origin: 'https://erp.example.test', protocol: 'https:' };
  globalThis.window = { frappe: { csrf_token: 'fixture-csrf', get_route: () => ['Form', 'Task', 'fixture'] } };
  globalThis.nativeClient = { registry: { mount() {} }, uiRevision: { bump() {} } };
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return new Response(JSON.stringify({ message: { status: 200, body: { ok: true } } }), { status: 200 });
  };
  const { api, pageContext, createHostClient } = await import(pathToFileURL(entry).href);
  assert.deepEqual(pageContext(), { route: ['Form', 'Task', 'fixture'], doctype: 'Task', name: 'fixture' });
  const config = { sessionCredential: 'fixture-session', controllerFenceToken: 'fixture-fence' };
  assert.equal(createHostClient({ config }, 'conversation', () => {}), globalThis.nativeClient);
  const proxy = globalThis.nativeConfig.fetchImpl;
  await assert.rejects(proxy('https://foreign.example/v1/tasks'), /无效/);
  await assert.rejects(proxy('/private/tasks'), /无效/);
  const cancelled = new AbortController(); cancelled.abort();
  await assert.rejects(proxy('/v1/tasks', { signal: cancelled.signal }), { name: 'AbortError' });
  await assert.rejects(api('frappe.client.delete'), /请求方法无效/);
  assert.equal(calls.length, 0);
  const response = await proxy('/v1/tasks?after=1', { method: 'POST', body: '{"action":"read"}' });
  assert.deepEqual(await response.json(), { ok: true });
  assert.equal(calls.length, 1, 'one original request, no automatic retry');
  assert.equal(calls[0].url, '/api/method/zebra_erpnext.api.client_proxy');
  assert.equal(calls[0].init.credentials, 'same-origin');
  assert.equal(calls[0].init.headers['X-Frappe-CSRF-Token'], 'fixture-csrf');
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    conversation: 'conversation', path: '/v1/tasks?after=1', method: 'POST', body: '{"action":"read"}',
    client_session: 'fixture-session', client_fence: 'fixture-fence',
  });
  assert.deepEqual(config, { sessionCredential: 'fixture-session', controllerFenceToken: 'fixture-fence' });
  console.log('PASS real Host adapter same-origin/CSRF/session/fence/abort and single submission');
} finally {
  esbuild.stop();
  rmSync(owned, { recursive: true, force: true });
}
