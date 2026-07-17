import type { SessionEvent, SessionStreamResponse } from "../types";
import { readSseEvents } from "./live-session";

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

interface EventStreamOptions {
  signal?: AbortSignal;
  afterSequence?: number;
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

export async function requestEventStream(
  baseUrl: string,
  path: string,
  authToken?: string,
  onEvent?: (event: SessionEvent) => void,
  options: EventStreamOptions = {},
): Promise<SessionStreamResponse> {
  const headers: Record<string, string> = {
    Accept: "text/event-stream",
  };
  if (authToken) {
    headers.Authorization = `Bearer ${authToken}`;
  }
  const cursor = options.afterSequence ?? -1;
  const separator = path.includes("?") ? "&" : "?";
  const response = await fetch(
    `${normalizeBaseUrl(baseUrl)}${path}${separator}after_sequence=${cursor}`,
    { headers, signal: options.signal },
  );
  if (!response.ok) {
    const raw = await response.text();
    let payload: unknown = raw;
    try {
      payload = JSON.parse(raw);
    } catch {
      // ponytail: backend returns JSON for non-stream failures; raw text fallback is enough here.
    }
    throw new ZebraApiError("Failed to read event stream", response.status, payload);
  }
  if (!response.body) throw new Error("Missing event stream body");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const events: SessionEvent[] = [];
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const parsed = readSseEvents(done ? `${buffer}\n\n` : buffer);
    buffer = parsed.remainder;
    parsed.events.forEach((event) => {
      events.push(event);
      onEvent?.(event);
    });
    if (done) break;
  }
  return {
    session_id: path.split("/")[2] ?? "",
    events,
  };
}
