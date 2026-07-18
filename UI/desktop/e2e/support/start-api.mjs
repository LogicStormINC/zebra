import { spawn } from "node:child_process";
import { mkdirSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const repositoryRoot = resolve(desktopRoot, "../..");
const runtimeRoot = resolve(desktopRoot, "test-results/runtime");
const databasePath = resolve(runtimeRoot, "sessions.sqlite");

mkdirSync(runtimeRoot, { recursive: true });
for (const suffix of ["", "-shm", "-wal"]) rmSync(`${databasePath}${suffix}`, { force: true });

const child = spawn(
  "uv",
  ["run", "--all-packages", "uvicorn", "zebra_agent_api.http:create_http_app", "--factory", "--host", "127.0.0.1", "--port", "18080"],
  {
    cwd: repositoryRoot,
    env: {
      ...process.env,
      ZEBRA_API_AUTH_TOKEN: "e2e-token",
      ZEBRA_DATABASE_URL: databasePath,
      ZEBRA_E2E_API_KEY: "e2e-secret",
      ZEBRA_MODEL_API_KEY_ENV: "ZEBRA_E2E_API_KEY",
      ZEBRA_MODEL_BASE_URL: "http://127.0.0.1:14010",
      ZEBRA_MODEL_MAX_RETRIES: "0",
      ZEBRA_MODEL_NAME: "e2e-stream",
      ZEBRA_MODEL_PROVIDER: "openai",
      ZEBRA_PROFILE: "local",
      ZEBRA_RUNTIME_CLASS: "trusted-local",
    },
    stdio: "inherit",
  },
);

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => child.kill(signal));
}
child.on("exit", (code) => process.exit(code ?? 1));
