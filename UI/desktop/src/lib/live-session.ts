import type { SessionEvent } from "../types";

export function mergeSessionEvents(current: SessionEvent[], incoming: SessionEvent[]): SessionEvent[] {
  const events = new Map(current.map((event) => [event.event_id, event]));
  incoming.forEach((event) => events.set(event.event_id, event));
  return [...events.values()].sort((left, right) => left.sequence - right.sequence);
}

export function readSseEvents(buffer: string): { events: SessionEvent[]; remainder: string } {
  const chunks = buffer.split(/\r?\n\r?\n/);
  const remainder = chunks.pop() ?? "";
  const events = chunks.flatMap((chunk) => {
    const data = chunk.split(/\r?\n/).find((line) => line.startsWith("data:"));
    return data ? [JSON.parse(data.slice(5).trim()) as SessionEvent] : [];
  });
  return { events, remainder };
}

export async function pollWhile<T>(operation: Promise<T>, refresh: () => Promise<unknown>, intervalMs = 500): Promise<T> {
  let stopped = false;
  const polling = (async () => {
    while (!stopped) {
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
      if (!stopped) await refresh().catch(() => undefined);
    }
  })();
  try {
    return await operation;
  } finally {
    stopped = true;
    await polling;
    await refresh();
  }
}
