import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const API_URL = "http://127.0.0.1:18080";
const AUTH_HEADERS = { Authorization: "Bearer e2e-token" };

test.beforeEach(async ({ page }) => {
  await page.addInitScript(({ apiUrl }) => {
    if (sessionStorage.getItem("zebra-e2e-configured")) return;
    localStorage.clear();
    localStorage.setItem(
      "zebra-agent-desktop.operator-config",
      JSON.stringify({ apiBaseUrl: apiUrl, authToken: "e2e-token", sessionId: "", userId: "", tenantId: "" }),
    );
    localStorage.setItem(
      "zebra-agent-desktop.task-launch-config",
      JSON.stringify({
        workspace: ".", policyProfile: "workspace_write", toolProfile: "coding", networkProfile: "none",
        networkAllowlist: [], mcpAllowlist: [], mcpResourceIds: [], mcpPromptId: null,
        mcpPromptArguments: {}, mcpPromptSchema: null,
      }),
    );
    sessionStorage.setItem("zebra-e2e-configured", "1");
  }, { apiUrl: API_URL });
  await page.goto("/");
  await expect(page.getByText("本地运行时已连接").first()).toBeVisible();
});

test("migrates the legacy no-network default to trusted read-only Web access", async ({ page }) => {
  await expect(page.getByRole("button", { name: "网络: 本地可信网络" })).toBeVisible();
});

test("shows the resolved Runtime class and no-silent-fallback policy", async ({ page }) => {
  await page.getByLabel("运行配置").click();
  await expect(page.getByText("Runtime 级别", { exact: true })).toBeVisible();
  await expect(page.getByText("trusted-local", { exact: true })).toBeVisible();
  await expect(page.getByText("禁止静默降级", { exact: true })).toBeVisible();
});

test("renders a long provider response progressively and converges durably", async ({ page }) => {
  await submit(page, "E2E_LONG_STREAM render every ordered fragment");

  await expect(page.getByText(/long-000\|/)).toBeVisible();
  await expect(page.getByText(/long-063\|/)).not.toBeVisible();
  await expect(page.getByText(/long-063\|/)).toBeVisible();
  await expect(page.getByText("已完成", { exact: true })).toBeVisible();

  expect(await assistantMarkers(page, "long")).toEqual(markers("long", 64));
});

test("reloads during a long stream and resumes without duplicate deltas", async ({ page }) => {
  await submit(page, "E2E_RECOVER_STREAM reload and continue from durable SSE history");
  await expect(page.getByText(/recover-005\|/)).toBeVisible();

  await page.reload();
  await expect(page.getByText(/recover-079\|/)).toBeVisible();
  await expect(page.getByText("已完成", { exact: true })).toBeVisible();

  expect(await assistantMarkers(page, "recover")).toEqual(markers("recover", 80));
});

test("stops a running stream without a late completion", async ({ page, request }) => {
  await submit(page, "E2E_STOP_STREAM cancel before the provider finishes");
  await expect(page.getByText(/stop-003\|/)).toBeVisible();
  const sessionId = await activeSessionId(page);

  await page.locator('[aria-label="停止任务"] button').click();
  await expect.poll(async () => (await session(request, sessionId)).status).toBe("cancelled");
  await expect(page.getByText("已停止", { exact: true })).toBeVisible();

  await page.waitForTimeout(5_000);
  const stream = await request.get(`${API_URL}/tasks/${sessionId}/stream`, { headers: AUTH_HEADERS });
  const events = await stream.text();
  expect(events).toContain('"event_type": "session_cancelled"');
  expect(events).not.toContain('"event_type": "session_completed"');
  expect((await session(request, sessionId)).status).toBe("cancelled");

  await submit(page, "E2E_APPROVAL continue the cancelled Task internally");
  await expect(page.getByText("Agent 需要人工确认")).toBeVisible();
  await page.getByRole("button", { name: "批准" }).click();
  await expect(page.getByText("APPROVAL_COMPLETE", { exact: true })).toBeVisible();
});

test("continues a completed task through an invisible internal Segment", async ({ page, request }) => {
  await submit(page, "E2E_FOLLOW_UP_ONE complete the first turn");
  await expect(page.getByText("FIRST_COMPLETE", { exact: true })).toBeVisible();
  await expect(page.getByText("已完成", { exact: true })).toBeVisible();
  const firstSessionId = await activeSessionId(page);

  await submit(page, "E2E_FOLLOW_UP_TWO continue after the terminal turn");
  await expect(page.getByText("SECOND_COMPLETE", { exact: true })).toBeVisible();
  await expect(page.getByText("E2E_FOLLOW_UP_TWO continue after the terminal turn", { exact: true })).toBeVisible();
  const secondSessionId = await activeSessionId(page);

  expect(secondSessionId).toBe(firstSessionId);
  expect((await session(request, firstSessionId)).status).toBe("completed");
  const internal = await request.get(`${API_URL}/internal/tasks/${firstSessionId}/segments`, { headers: AUTH_HEADERS });
  expect(internal.ok()).toBeTruthy();
  expect((await internal.json()).segments).toHaveLength(2);
});

test("shows and completes a real approval continuation", async ({ page }) => {
  await submit(page, "E2E_APPROVAL browser approval");
  await expect(page.getByText("Agent 需要人工确认")).toBeVisible();
  await expect(page.getByLabel("需要人工确认").getByText("command.run", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "批准" }).click();
  await expect(page.getByText("APPROVAL_COMPLETE", { exact: true })).toBeVisible();
  await expect(page.getByText("已完成", { exact: true })).toBeVisible();
});

test("renders a provider failure as a terminal operator state", async ({ page }) => {
  await submit(page, "E2E_FAILURE browser failure");
  await expect(page.getByText("任务执行失败", { exact: true })).toBeVisible();
  await expect(page.getByText("失败", { exact: true })).toBeVisible();
});

async function submit(page: Page, prompt: string) {
  const composer = page.locator('textarea[name="task-prompt"]');
  await composer.fill(prompt);
  await page.getByLabel("发送任务").click();
}

async function activeSessionId(page: Page): Promise<string> {
  return page.evaluate(() => {
    const raw = localStorage.getItem("zebra-agent-desktop.operator-config");
    return raw ? String(JSON.parse(raw).sessionId ?? "") : "";
  });
}

async function assistantMarkers(page: Page, prefix: string): Promise<string[]> {
  const assistant = page.locator("section").filter({ hasText: "Zebra Agent" }).last();
  const text = await assistant.textContent();
  return text?.match(new RegExp(`${prefix}-\\d{3}\\|`, "g")) ?? [];
}

function markers(prefix: string, count: number): string[] {
  return Array.from({ length: count }, (_, index) => `${prefix}-${String(index).padStart(3, "0")}|`);
}

async function session(request: APIRequestContext, sessionId: string): Promise<{ status: string }> {
  const response = await request.get(`${API_URL}/tasks/${sessionId}`, { headers: AUTH_HEADERS });
  expect(response.ok()).toBeTruthy();
  return response.json() as Promise<{ status: string }>;
}
