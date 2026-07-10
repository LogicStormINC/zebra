import type { SessionEvent, SessionStreamResponse } from "../types";

export class ZebraApiError extends Error {
  statusCode: number;
  payload: unknown;

  constructor(message: string, statusCode: number, payload: unknown) {
    super(message);
    this.name = "ZebraApiError";
    this.statusCode = statusCode;
    this.payload = payload;
  }
}

interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  authToken?: string;
}

function normalizeBaseUrl(baseUrl: string) {
  return baseUrl.trim().replace(/\/+$/, "");
}

export async function requestJson<T>(
  baseUrl: string,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
  };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (options.authToken) {
    headers.Authorization = `Bearer ${options.authToken}`;
  }

  const response = await fetch(`${normalizeBaseUrl(baseUrl)}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const reason =
      typeof payload === "object" && payload && "reason" in payload
        ? String(payload.reason)
        : response.statusText;
    throw new ZebraApiError(reason || "Request failed", response.status, payload);
  }
  return payload as T;
}

function parseEventStream(raw: string): SessionEvent[] {
  return raw
    .split("\n\n")
    .map((chunk) => chunk.trim())
    .filter(Boolean)
    .map((chunk) => {
      const dataLine = chunk
        .split("\n")
        .find((line) => line.startsWith("data: "));
      if (!dataLine) {
        throw new Error("Missing SSE data payload");
      }
      return JSON.parse(dataLine.slice(6)) as SessionEvent;
    });
}

export async function requestEventStream(
  baseUrl: string,
  path: string,
  authToken?: string,
): Promise<SessionStreamResponse> {
  const headers: Record<string, string> = {
    Accept: "text/event-stream",
  };
  if (authToken) {
    headers.Authorization = `Bearer ${authToken}`;
  }
  const response = await fetch(`${normalizeBaseUrl(baseUrl)}${path}`, { headers });
  const raw = await response.text();
  if (!response.ok) {
    let payload: unknown = raw;
    try {
      payload = JSON.parse(raw);
    } catch {
      // ponytail: backend returns JSON for non-stream failures; raw text fallback is enough here.
    }
    throw new ZebraApiError("Failed to read event stream", response.status, payload);
  }
  return {
    session_id: path.split("/")[2] ?? "",
    events: parseEventStream(raw),
  };
}
