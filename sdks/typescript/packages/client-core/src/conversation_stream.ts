/** Advertise only when the Host uses the v2 observer and visible draft label. */
export const STREAM_V2_CAPABILITIES = Object.freeze({
  wire_version: 2 as const,
  provisional_draft_label: true,
  replace_message: true,
  reset_provisional: true,
  scoped_resume: true,
});

/** Transport observations reduce to Host-controlled messages; commits remain canonical. */
export interface ConversationMessage {
  id: string;
  role: "assistant";
  content: string;
  status: "streaming" | "complete";
  presentation: "provisional" | "committed";
}

export interface ConversationStreamEvent {
  /** Transport cursor distinguishes separate replacement sequences with the same message ID. */
  streamCursor?: string;
  type?: string;
  name?: string;
  value?: unknown;
  messageId?: string;
  delta?: unknown;
}

interface Draft {
  generation: string;
  offset: number;
}

export class ConversationStreamReducer {
  private contentBytes = 0;
  private readonly encoder = new TextEncoder();
  private readonly messageBytes = new Map<string, number>();
  private lastChunk: { key: string; payload: string; draft: boolean } | undefined;
  private readonly messages = new Map<string, ConversationMessage>();
  private readonly draftChunks = new Map<string, { generation: string; offset: number; parts: string[] }>();
  private readonly drafts = new Map<string, Draft>();
  private readonly canonical = new Set<string>();
  private readonly replacements = new Map<string, { offset: number; content: string }>();

  snapshot(): readonly ConversationMessage[] {
    return [...this.messages.values()];
  }

  reset(): void {
    this.lastChunk = undefined;
    this.messages.clear();
    this.messageBytes.clear();
    this.contentBytes = 0;
    this.drafts.clear();
    this.draftChunks.clear();
    this.canonical.clear();
    this.replacements.clear();
  }

  observe(event: ConversationStreamEvent): void {
    const value = isObject(event.value) ? event.value : null;
    const chunk = event.type === "CUSTOM" && value && value.chunk_index !== undefined &&
      (event.name === "zebra.stream.draft" || event.name === "zebra.message_replace");
    const key = chunk ? JSON.stringify(event.streamCursor !== undefined
      ? [event.streamCursor]
      : [event.name, value.message_id, value.generation_id, value.offset, value.chunk_index]) : null;
    const payload = key ? JSON.stringify(event) : null;
    if (key && this.lastChunk?.key === key) {
      if (this.lastChunk.payload !== payload) throw new Error("Conflicting unacknowledged chunk");
      return;
    }
    this.apply(event);
    // One replay slot covers the only record that can fail its awaited Host ACK.
    if (key && payload) this.lastChunk = { key, payload, draft: event.name === "zebra.stream.draft" };
    else if (!event.name?.startsWith("zebra.stream.")) this.lastChunk = undefined;
  }

  private apply(event: ConversationStreamEvent): void {
    if (event.type !== "CUSTOM" || !isObject(event.value)) return;
    const value = event.value;
    if (event.name === "zebra.stream.recovery_start") {
      this.reset();
      return;
    }
    if (event.name === "zebra.stream.reset") {
      if (this.lastChunk?.draft) this.lastChunk = undefined;
      for (const id of this.drafts.keys()) if (!this.canonical.has(id)) this.remove(id);
      this.drafts.clear();
      this.draftChunks.clear();
      return;
    }
    if (event.name === "zebra.stream.draft") {
      const id = text(value.message_id);
      const generation = text(value.generation_id);
      let content = text(value.content_delta, true);
      const offset = value.offset;
      if (!id || !generation || content === null || !Number.isSafeInteger(offset) || (offset as number) < 0) {
        throw new Error("Invalid provisional frame");
      }
      if (this.canonical.has(id)) return;
      if (value.chunk_index !== undefined) {
        if (!Number.isSafeInteger(value.chunk_index) || (value.chunk_index as number) < 0 || typeof value.last !== "boolean") throw new Error("Invalid draft chunk");
        const index = value.chunk_index as number;
        if (index === 0 && !this.draftChunks.has(id) && this.draftChunks.size >= 8) throw new Error("Draft assembly capacity exceeded");
        if (index === 0) this.draftChunks.set(id, { generation, offset: offset as number, parts: [] });
        const staged = this.draftChunks.get(id);
        if (!staged || staged.generation !== generation || staged.offset !== offset || index > staged.parts.length || index >= 16) throw new Error("Draft chunk gap");
        if (index < staged.parts.length && staged.parts[index] !== content) throw new Error("Conflicting draft chunk");
        if (index === staged.parts.length) staged.parts.push(content);
        if (staged.parts.reduce((size, part) => size + part.length, 0) > 16384) throw new Error("Draft assembly exceeds bounds");
        if (!value.last) return;
        content = staged.parts.join("");
        this.draftChunks.delete(id);
      }

      const current = this.drafts.get(id);
      if (current?.generation === generation && (offset as number) <= current.offset) return;
      if ((!current || current.generation !== generation) && offset !== 0) throw new Error("Draft prefix unavailable");
      if (current?.generation === generation && offset !== current.offset + 1) throw new Error("Draft offset gap");
      const previous = current?.generation === generation ? this.messages.get(id)?.content ?? "" : "";
      this.put(id, previous + content, "provisional", "streaming", current?.generation === generation ? content : undefined);
      this.drafts.set(id, { generation, offset: offset as number });
      return;
    }
    if (event.name === "zebra.message_replace") {
      const id = text(value.message_id);
      const content = text(value.content, true);
      const offset = value.chunk_index;
      if (!id || content === null || !Number.isSafeInteger(offset) || (offset as number) < 0 || typeof value.last !== "boolean") {
        throw new Error("Invalid canonical replacement");
      }
      if (this.messages.get(id)?.presentation === "committed") return;
      let current = this.replacements.get(id);
      if (offset === 0) {
        if (!this.replacements.has(id) && this.replacements.size >= 8) throw new Error("Replacement assembly capacity exceeded");
        current = { offset: -1, content: "" };
        this.replacements.set(id, current);
        if (!this.canonical.has(id) && this.canonical.size >= 500) throw new Error("Canonical message capacity exceeded");
        this.canonical.add(id); // Late visual frames cannot resurrect a completed callback.
        this.drafts.delete(id);
        this.draftChunks.delete(id);
      }
      if (!current || offset !== current.offset + 1) throw new Error("Replacement offset gap");
      current.offset = offset as number;
      current.content += content;
      if (current.content.length > 1_048_576) throw new Error("Replacement exceeds text budget");
      if (value.last) {
        if (current.content) this.put(id, current.content, "provisional", "complete");
        else this.remove(id);
        this.replacements.delete(id);
      }
      return;
    }
    if (event.name === "zebra.answer_committed") {
      const call = text(value.model_call_id);
      const id = call ? `message:${call}` : text(value.message_id);
      if (!id || !id.startsWith("message:") || id.length > 4096) throw new Error("Committed answer identity is unavailable");
      const content = value.replacement_committed === true
        ? this.messages.get(id)?.content ?? null
        : text(value.assistant_message);
      if (!content) throw new Error("Committed answer is unavailable");
      if (!this.canonical.has(id) && this.canonical.size >= 500) throw new Error("Canonical message capacity exceeded");
      this.canonical.add(id);
      this.drafts.delete(id);
      this.replacements.delete(id);
      this.put(id, content, "committed", "complete");
    }
  }

  private remove(id: string): void {
    this.contentBytes -= this.messageBytes.get(id) ?? 0;
    this.messageBytes.delete(id);
    this.messages.delete(id);
  }

  private put(id: string, content: string, presentation: ConversationMessage["presentation"], status: ConversationMessage["status"], appended?: string): void {
    if (content.length > 1_048_576 || (!this.messages.has(id) && this.messages.size >= 500)) throw new Error("Conversation exceeds bounded recovery capacity");
    const previousBytes = this.messageBytes.get(id) ?? 0;
    // ponytail: encode only new text; a surrogate pair split across frames replaces two 3-byte errors.
    let bytes = appended === undefined ? this.encoder.encode(content).length : previousBytes + this.encoder.encode(appended).length;
    if (appended?.length && content.length > appended.length) {
      const high = content.charCodeAt(content.length - appended.length - 1);
      const low = appended.charCodeAt(0);
      if (high >= 0xd800 && high <= 0xdbff && low >= 0xdc00 && low <= 0xdfff) bytes -= 2;
    }
    const total = this.contentBytes - previousBytes + bytes;
    if (total > 8 * 1024 * 1024) throw new Error("Conversation byte capacity exceeded");
    this.contentBytes = total;
    this.messageBytes.set(id, bytes);
    this.messages.set(id, { id, role: "assistant", content, presentation, status });
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function text(value: unknown, allowEmpty = false): string | null {
  return typeof value === "string" && (allowEmpty || value.length > 0) ? value : null;
}


export interface StreamObserverOptions {
  streamVersion?: 2 | undefined;
  onObservation?: ((event: ConversationStreamEvent) => Promise<void>) | undefined;
}

export function streamObserverOptions(options: StreamObserverOptions) {
  return {
    ...(options.streamVersion === 2 ? { streamVersion: 2 as const } : {}),
    ...(options.onObservation ? { onObservation: options.onObservation } : {}),
  };
}
