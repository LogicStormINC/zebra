import type { ClientEffectWire } from "@zebra-agent/contracts";

export async function consumeClientEffectStream(options: {
  fetchImpl: typeof fetch;
  streamUrl: string;
  headers: () => Record<string, string>;
  stopped: () => boolean;
  signal: AbortSignal;
  initialEventId?: string | null;
  onCursor?: (eventId: string | null) => void;
  onCursorRecovered?: () => Promise<void>;
  onTerminalRejection?: () => void;
  onEffect: (effect: ClientEffectWire) => Promise<void>;
}): Promise<void> {
  let lastEventId: string | null = options.initialEventId ?? null;
  while (!options.stopped() && !options.signal.aborted) {
    try {
      const headers = options.headers();
      headers.Accept = "text/event-stream";
      if (lastEventId !== null) headers["Last-Event-ID"] = lastEventId;
      const response = await options.fetchImpl(options.streamUrl, {
        headers,
        signal: options.signal,
      });
      if ([401, 403, 410].includes(response.status)) {
        options.onTerminalRejection?.();
        return;
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
      lastEventId = await readSse(response.body, options, lastEventId);
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
      typeof payload.recovery_cursor === "string" &&
      payload.recovery_cursor.length > 0
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
): Promise<string | null> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let lastEventId = initialEventId;
  while (!options.signal.aborted) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer = (buffer + decoder.decode(value, { stream: true })).replaceAll("\r\n", "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const record = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const nextEventId = await handleRecord(record, options.onEffect, lastEventId);
      if (nextEventId !== null && nextEventId !== lastEventId) {
        options.onCursor?.(nextEventId);
      }
      lastEventId = nextEventId;
      boundary = buffer.indexOf("\n\n");
    }
  }
  return lastEventId;
}

async function handleRecord(
  record: string,
  onEffect: (effect: ClientEffectWire) => Promise<void>,
  lastEventId: string | null,
): Promise<string | null> {
  let data = "";
  let eventId: string | null = null;
  for (const line of record.split("\n")) {
    if (line.startsWith("id:")) eventId = line.slice(3).trim();
    if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (data === "") return lastEventId;
  const event = JSON.parse(data) as {
    type?: string;
    delta?: Array<{
      op?: string;
      value?: ClientEffectWire & { execution_location?: string };
    }>;
  };
  if (event.type !== "STATE_DELTA") return eventId ?? lastEventId;
  for (const operation of event.delta ?? []) {
    const effect = operation.value;
    if (
      operation.op === "add" &&
      effect?.execution_location === "client" &&
      effect.status === "pending"
    ) {
      await onEffect(effect);
    }
  }
  return eventId ?? lastEventId;
}
