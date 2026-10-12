import type { ConversationStreamEvent } from "./conversation_stream.ts";
import { isStreamCursor } from "./runtime_state.ts";
import type { ClientEffectWire } from "@zebra-agent/contracts";

export async function consumeClientEffectStream(options: {
  fetchImpl: typeof fetch;
  streamUrl: string;
  headers: () => Record<string, string>;
  stopped: () => boolean;
  signal: AbortSignal;
  initialEventId?: string | null;
  streamVersion?: 2;
  onObservation?: (event: ConversationStreamEvent) => Promise<void>;
  onCursor?: (eventId: string | null) => void;
  onCursorRecovered?: () => Promise<void>;
  onTerminalRejection?: () => void;
  onEffect: (effect: ClientEffectWire) => Promise<void>;
}): Promise<void> {
  let lastEventId: string | null = options.initialEventId ?? null;
  const recovery: StreamReadState = { active: options.streamVersion === 2 };
  while (!options.stopped() && !options.signal.aborted) {
    try {
      if (options.streamVersion === 2 && lastEventId === null) recovery.active = true;
      const headers = options.headers();
      headers.Accept = "text/event-stream";
      if (lastEventId !== null) headers["Last-Event-ID"] = lastEventId;
      const url = recovery.active
        ? `${options.streamUrl}${options.streamUrl.includes("?") ? "&" : "?"}recovery=full`
        : options.streamUrl;
      if (recovery.active) delete headers["Last-Event-ID"];
      const response = await options.fetchImpl(url, {
        headers,
        signal: options.signal,
      });
      const terminal = [401, 403, 410].includes(response.status) ||
        (response.status === 400 && lastEventId === null && options.streamVersion === 2);
      if ([400, 401, 403, 410].includes(response.status) && options.streamVersion === 2) {
        lastEventId = null;
        try {
          options.onCursor?.(null);
          await options.onObservation?.({ type: "CUSTOM", name: "zebra.stream.reset", value: { reason: "authorization_rejected" } });
        } catch { /* A Host teardown failure cannot extend rejected stream authority. */ }
        if (!terminal) { recovery.active = true; continue; }
      }
      if (terminal) {
        try { options.onTerminalRejection?.(); } finally { return; }
      }
      if (response.status === 400 && lastEventId !== null) {
        const replacement = await invalidCursorReplacement(response);
        if (replacement !== null) {
          lastEventId = replacement;
          options.onCursor?.(replacement);
          await options.onCursorRecovered?.();
          continue;
        }
        options.onTerminalRejection?.();
        return;
      }
      if (!response.ok || response.body === null) throw new Error("SSE unavailable");
      lastEventId = await readSse(response.body, { ...options, onCursor: (cursor) => {
        lastEventId = cursor;
        options.onCursor?.(cursor);
      } }, lastEventId, recovery);
    } catch {
      if (options.signal.aborted || options.stopped()) return;
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  }
}

async function invalidCursorReplacement(response: Response): Promise<string | null> {
  try {
    const payload = (await response.json()) as {
      code?: unknown;
      recovery_cursor?: unknown;
    };
    return payload.code === "invalid_cursor" &&
      isStreamCursor(payload.recovery_cursor)
      ? payload.recovery_cursor
      : null;
  } catch {
    return null;
  }
}

async function readSse(
  body: ReadableStream<Uint8Array>,
  options: Parameters<typeof consumeClientEffectStream>[0],
  initialEventId: string | null,
  recovery: StreamReadState,
): Promise<string | null> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let lastEventId = initialEventId;
  const recordLimit = options.streamVersion === 2 ? 16384 : 8_388_608;
  try {
    while (!options.signal.aborted) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer = (buffer + decoder.decode(value, { stream: true })).replaceAll("\r\n", "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        if (boundary > recordLimit) throw new Error("SSE record exceeds bounded compatibility budget");
        const record = buffer.slice(0, boundary);
        if (new TextEncoder().encode(record).length > recordLimit) throw new Error("SSE record exceeds byte budget");
        buffer = buffer.slice(boundary + 2);
        const nextEventId = await handleRecord(record, options, lastEventId, recovery);
        if (nextEventId !== null && nextEventId !== lastEventId) {
          options.onCursor?.(nextEventId);
        }
        lastEventId = nextEventId;
        boundary = buffer.indexOf("\n\n");
      }
      if (buffer.length > recordLimit || new TextEncoder().encode(buffer).length > recordLimit) throw new Error("SSE record exceeds bounded compatibility budget");
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
  return lastEventId;
}

async function handleRecord(
  record: string,
  options: Parameters<typeof consumeClientEffectStream>[0],
  lastEventId: string | null,
  recovery: StreamReadState,
): Promise<string | null> {
  let data = "";
  let eventId: string | null = null;
  for (const line of record.split("\n")) {
    if (line.startsWith("id:")) eventId = line.slice(3).trim();
    if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (data === "") return lastEventId;
  if (eventId !== null && !isStreamCursor(eventId)) throw new Error("SSE cursor exceeds bounds");
  let event = JSON.parse(data) as ConversationStreamEvent & {
    type?: string;
    delta?: Array<{
      op?: string;
      value?: ClientEffectWire & { execution_location?: string };
    }>;
  };
  let assembled = false;
  if (event.type === "CUSTOM" && event.name === "zebra.canonical_chunk") {
    const value = event.value as { chunk_index?: unknown; content?: unknown; last?: unknown };
    if (!Number.isSafeInteger(value.chunk_index) || typeof value.content !== "string" || typeof value.last !== "boolean") throw new Error("Invalid canonical chunk");
    const index = value.chunk_index as number;
    if (index === 0 && !recovery.chunks) recovery.chunks = [];
    const chunks = recovery.chunks;
    if (!chunks || index > chunks.length || index < 0 || index >= 4096) throw new Error("Canonical chunk gap");
    if (index < chunks.length && (chunks[index]?.content !== value.content || chunks[index]?.last !== value.last)) throw new Error("Conflicting canonical chunk");
    if (index === chunks.length) {
      if (chunks.at(-1)?.last) throw new Error("Canonical chunk after final");
      chunks.push({ content: value.content, last: value.last });
    }
    if (chunks.reduce((length, part) => length + part.content.length, 0) > 2_097_152) throw new Error("Canonical assembly exceeds bounds");
    if (!value.last) return eventId ?? lastEventId;
    event = JSON.parse(chunks.map(part => part.content).join("")) as typeof event;
    assembled = true;
  }
  if (event.type === "CUSTOM" && event.name === "zebra.stream.recovery_start") delete recovery.chunks;
  if (options.streamVersion === 2 && event.type === "CUSTOM" && event.name === "zebra.stream.reset") {
    // Discarding continuation is safe even if the Host reset callback fails.
    options.onCursor?.(null);
    await options.onObservation?.(event);
    if (assembled) delete recovery.chunks;
    return null; // Current live handling stays active; only a reconnect starts cold recovery.
  }
  await options.onObservation?.(event);
  if (event.type === "CUSTOM" && event.name === "zebra.stream.recovery_start") recovery.active = true;
  if (event.type === "CUSTOM" && event.name === "zebra.stream.recovery_complete") {
    await options.onCursorRecovered?.(); // Current pending set, never historical add operations.
    recovery.active = false;
  }
  for (const operation of event.type === "STATE_DELTA" ? event.delta ?? [] : []) {
    const effect = operation.value;
    if (
      !recovery.active &&
      operation.op === "add" &&
      effect?.execution_location === "client" &&
      effect.status === "pending"
    ) {
      await options.onEffect(effect);
    }
  }
  if (assembled) delete recovery.chunks; // Prefix retires only after every awaited callback ACK.
  return eventId ?? lastEventId;
}

interface StreamReadState {
  active: boolean;
  chunks?: Array<{ content: string; last: boolean }>;
}
