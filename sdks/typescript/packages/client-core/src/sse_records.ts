/** A framing violation is permanent: reconnecting cannot repair poisoned wire bytes. */
export class SseProtocolError extends Error {}
export interface SseRecord { data: string; id: string | null }

/** Pull one bounded UTF-8 record at a time; application controls the next reader pull. */
export async function* readSseRecords(body: ReadableStream<Uint8Array>, maxBytes: number, signal?: AbortSignal): AsyncGenerator<SseRecord> {
  if (!Number.isSafeInteger(maxBytes) || maxBytes <= 0) throw new RangeError("Invalid SSE byte budget");
  const reader = body.getReader();
  const abort = () => { void reader.cancel(signal?.reason).catch(() => undefined); };
  signal?.addEventListener("abort", abort, { once: true });
  const decoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });
  let line = new Uint8Array(Math.min(1024, maxBytes));
  let length = 0, recordBytes = 0, skipLf = false, first = true;
  let data: string[] = [], id: string | null = null;
  const finishLine = (): SseRecord | undefined => {
    let text: string;
    try { text = decoder.decode(line.subarray(0, length)); }
    catch { throw new SseProtocolError("Invalid UTF-8 in SSE stream"); }
    if (first) { text = text.replace(/^\uFEFF/, ""); first = false; }
    length = 0;
    if (text === "") {
      const result = data.length ? { data: data.join("\n"), id } : undefined;
      data = []; id = null; recordBytes = 0;
      return result;
    }
    const separator = text.indexOf(":");
    const field = separator < 0 ? text : text.slice(0, separator);
    let value = separator < 0 ? "" : text.slice(separator + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "data") data.push(value);
    if (field === "id" && !value.includes("\0")) id = value;
    return undefined;
  };
  try {
    while (!signal?.aborted) {
      const next = await reader.read();
      if (signal?.aborted) return;
      if (next.done) {
        if (skipLf) { const record = finishLine(); if (record) yield record; }
        if (length || data.length) throw new SseProtocolError("Truncated SSE record");
        return;
      }
      for (const byte of next.value) {
        if (skipLf) {
          skipLf = false;
          if (byte === 10 && ++recordBytes > maxBytes) throw new SseProtocolError("SSE record exceeds byte budget");
          const record = finishLine();
          if (record) yield record;
          if (byte === 10) continue;
        }
        if (++recordBytes > maxBytes) throw new SseProtocolError("SSE record exceeds byte budget");
        if (byte === 13) { skipLf = true; }
        else if (byte === 10) {
          const record = finishLine();
          if (record) yield record;
        } else {
          if (length === line.length) {
            const grown = new Uint8Array(Math.min(maxBytes, line.length * 2));
            grown.set(line); line = grown;
          }
          line[length++] = byte;
        }
      }
    }
  } finally {
    signal?.removeEventListener("abort", abort);
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
