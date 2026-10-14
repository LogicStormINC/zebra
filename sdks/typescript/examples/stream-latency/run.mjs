import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
const require = createRequire(new URL("../../package.json", import.meta.url));
const esbuild = require(require.resolve("esbuild", { paths: [dirname(require.resolve("tsx/package.json"))] }));
const output = await mkdtemp(join(tmpdir(), "zebra-stream-example-"));
await esbuild.build({
  entryPoints: [fileURLToPath(new URL("app.tsx", import.meta.url))], bundle: true,
  outfile: join(output, "app.js"), platform: "browser", format: "esm",
  nodePaths: [fileURLToPath(new URL("../../packages/react/node_modules", import.meta.url)), fileURLToPath(new URL("../../packages/react-charts/node_modules", import.meta.url))],
});
const html = '<!doctype html><meta charset="utf-8"><title>Cloud Agent stream replay</title><link rel="stylesheet" href="/app.css"><div id="root"></div><script type="module" src="/app.js"></script>';
const server = createServer(async (request, response) => {
  const path = request.url?.split("?")[0];
  if (path === "/") { response.setHeader("Content-Type", "text/html"); response.end(html); return; }
  if (path !== "/app.js" && path !== "/app.css") { response.writeHead(404).end(); return; }
  response.setHeader("Content-Type", path.endsWith(".css") ? "text/css" : "text/javascript");
  response.end(await readFile(join(output, path.slice(1))));
});
server.listen(0, "127.0.0.1", () => console.log(`Standalone replay: http://127.0.0.1:${server.address().port}`));
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => { server.close(); void rm(output, { recursive: true, force: true }).finally(() => process.exit()); });
