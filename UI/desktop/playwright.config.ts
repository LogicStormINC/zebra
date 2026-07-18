import { defineConfig, devices } from "@playwright/test";

const CI = Boolean(process.env.CI);

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 25_000 },
  reporter: CI ? [["line"], ["html", { open: "never" }]] : "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: "http://127.0.0.1:14173",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  webServer: [
    {
      command: "node e2e/support/mock-provider.mjs",
      port: 14_010,
      reuseExistingServer: false,
      timeout: 10_000,
    },
    {
      command: "node e2e/support/start-api.mjs",
      url: "http://127.0.0.1:18080/health",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "pnpm dev --host 127.0.0.1 --port 14173",
      url: "http://127.0.0.1:14173",
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
