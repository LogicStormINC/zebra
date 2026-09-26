import { readFile } from "node:fs/promises";
import { chromium } from "@playwright/test";

const [phase, seedPath] = process.argv.slice(2);
if (!phase || !seedPath) throw new Error("usage: run.mjs <first|replay> <seed.json>");
const seed = JSON.parse(await readFile(seedPath, "utf8"));
const apiPort = Number(process.env.ZEBRA_TEST_API_PORT ?? "18082");
const origin = `http://127.0.0.1:${apiPort}`;
const root = new URL("../../", import.meta.url);
const [clientCore, contracts] = await Promise.all([
  readFile(new URL("packages/client-core/dist/index.js", root), "utf8"),
  readFile(new URL("packages/contracts/dist/index.js", root), "utf8"),
]);
const context = await chromium.launchPersistentContext(
  process.env.ZEBRA_TEST_BROWSER_PROFILE,
  { headless: true },
);
const page = await context.newPage();
page.on("console", (message) => console.error(`browser console: ${message.text()}`));
page.on("pageerror", (error) => console.error(`browser error: ${error.message}`));
await page.route(`${origin}/client-core.js`, async (route) => {
  await route.fulfill({ body: clientCore, contentType: "text/javascript" });
});
await page.route(`${origin}/contracts.js`, async (route) => {
  await route.fulfill({ body: contracts, contentType: "text/javascript" });
});
await page.route(`${origin}/browser`, async (route) => {
  const url = route.request().url();
  if (!url.endsWith("/browser")) throw new Error(`unexpected browser URL: ${url}`);
  await route.fulfill({
    body: `<!doctype html><main id="status">starting</main>
      <script type="importmap">{"imports":{"@zebra-agent/contracts":"${origin}/contracts.js"}}</script>
      <script type="module" src="${origin}/app.js"></script>`,
    contentType: "text/html",
  });
});
await page.route(`${origin}/app.js`, async (route) => {
  const config = JSON.stringify({
    baseUrl: `http://127.0.0.1:${apiPort}`,
    clientSessionId: seed.client_session_id,
    sessionCredential: seed.session_credential,
    controllerFenceToken: seed.fence_token,
    taskId: seed.task_id,
    runId: seed.run_id,
    runBindingId: "11111111-1111-4111-8111-111111111111",
    clientBindingDigest: seed.binding_digest,
    actionContractDigests: { [seed.action_name]: seed.action_contract_digest },
  });
  await route.fulfill({
    contentType: "text/javascript",
    body: `
      import { ZebraClientRuntime } from "${origin}/client-core.js";
      const status = document.querySelector("#status");
      let handlerCalls = 0;
      const runtime = ZebraClientRuntime.fromConfig({ ...${config}, storage: localStorage });
      runtime.registry.mount(${JSON.stringify(seed.action_name)}, () => {
        handlerCalls += 1;
        return { opened: true };
      });
      await runtime.mount({
        frontendAppId: ${JSON.stringify(seed.frontend_app_id)},
        profileRevision: ${JSON.stringify(seed.profile_revision)},
        profileDigest: ${JSON.stringify(seed.profile_digest)},
        mountedActions: [${JSON.stringify(seed.action_name)}],
      });
      await runtime.start();
      await new Promise((resolve) => setTimeout(resolve, 4200));
      runtime.stop();
      status.dataset.ready = "true";
      status.dataset.handlerCalls = String(handlerCalls);
    `,
  });
});
try {
  await page.goto(`${origin}/browser`);
  await page.locator("#status[data-ready='true']").waitFor({ timeout: 15_000 });
  const calls = Number(await page.locator("#status").getAttribute("data-handler-calls"));
  const expected = phase === "first" ? 1 : 0;
  if (calls !== expected) throw new Error(`${phase}: expected ${expected} handler call(s), got ${calls}`);
  console.log(`ZEBRA_BROWSER_RECONNECT_${phase.toUpperCase()}=PASS`);
} finally {
  await context.close();
}
