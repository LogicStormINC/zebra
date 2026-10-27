/** Durable non-authoritative locators only. Original requests belong to the trusted BFF. */
import { ClientRuntimeError } from "./errors.ts";
import { readClientJson } from "./runtime_transport.ts";
const uuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value) && value !== "00000000-0000-0000-0000-000000000000";
const fail = (): never => { throw new ClientRuntimeError("command_recovery_unavailable", "durable command recovery unavailable; preserve original identity"); };
export interface CommandRecoveryView {
  pending(): readonly string[];
  reconcile(key: string): Promise<{status: "accepted"; commandId: string} | {status: "unknown"}>;
}
export class CommandRecovery implements CommandRecoveryView {
  private readonly key: string;
  constructor(private readonly storage: Storage | undefined, session: string, task: string, run: string, private readonly request: typeof fetch, private readonly path: string) {
    this.key = `zebra:command-recovery:${session}:${task}:${encodeURIComponent(run)}`;
    this.pending();
  }
  pending(): string[] {
    try {
      if (!this.storage) return fail();
      const raw = this.storage.getItem(this.key);
      if (raw === null) return [];
      if (raw.length > 2048) return fail();
      const keys: unknown = JSON.parse(raw);
      if (!Array.isArray(keys) || keys.length > 16 || keys.some(k => !uuid(k)) || new Set(keys).size !== keys.length) return fail();
      return keys as string[];
    } catch { return fail(); }
  }
  ensureClear(): void { if (this.pending().length) throw new ClientRuntimeError("command_recovery_pending", "reconcile original command before mount or dispatch"); }
  add(key: string): void {
    if (!uuid(key)) return fail();
    this.ensureClear(); this.write([key]);
  }
  private write(keys: string[]): void {
    const raw = JSON.stringify(keys);
    try { this.storage!.setItem(this.key, raw); if (this.storage!.getItem(this.key) !== raw) fail(); } catch { fail(); }
  }
  complete(key: string): void { this.write(this.pending().filter(k => k !== key)); }
  async reconcile(key: string): Promise<{status: "accepted"; commandId: string} | {status: "unknown"}> {
    if (!uuid(key) || !this.pending().includes(key)) return fail();
    try {
      const response = await this.request(this.path, {method: "GET", headers: {"Idempotency-Key": key}});
      if (!response.ok) return fail();
      const result = await readClientJson(response, 4096) as Record<string, unknown>;
      if (!result || typeof result !== "object" || Array.isArray(result)) return fail();
      if (result.status === "unknown" && Object.keys(result).length === 1) return {status: "unknown"};
      if (result.status !== "accepted" || !uuid(result.commandId) || Object.keys(result).length !== 2) return fail();
      this.complete(key); return {status: "accepted", commandId: result.commandId};
    } catch { return fail(); }
  }
}

/** One attempt; the callback persists the locator only after request validation. */
export async function submitRecoverableCommand<T>(recovery: CommandRecovery | null, key: string,
  send: (beforeDispatch?: () => void) => Promise<T>, disconnect: () => void): Promise<T> {
  recovery?.ensureClear(); let dispatched = false;
  try {
    const result = await send(() => { recovery?.add(key); dispatched = true; });
    recovery?.complete(key); return result;
  } catch (error) {
    if (recovery && dispatched || error instanceof ClientRuntimeError && error.code === "readable_command_unknown") disconnect();
    throw error;
  }
}
