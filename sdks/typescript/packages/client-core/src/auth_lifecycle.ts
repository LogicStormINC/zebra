/** Opt-in local lifecycle only. Business BFF and native Runtime remain admission authorities. */
import type {createBFFAuth, BFFAuthState} from "./bff_auth.ts";
import {ClientRuntimeError} from "./errors.ts";
type Auth = ReturnType<typeof createBFFAuth>;
export type AuthenticatedRuntimeOptions<T, R extends {stop(): void; readonly isStopped: boolean}> = {
  auth: Auth;
  /** Same-origin, no-secret browser bootstrap; respect AbortSignal and BFF Access gating. */
  bootstrap(signal: AbortSignal): Promise<T>;
  /** Synchronous construction; real ZebraClientRuntime.fromConfig validates BFF config. */
  create(bootstrap: T): R;
  mount(runtime: R, bootstrap: T, signal: AbortSignal): Promise<void>;
};
/** All starts are explicit. No timer, retry, token storage or native authority is added. */
export function createAuthenticatedRuntime<T, R extends {stop(): void; readonly isStopped: boolean}>(options: AuthenticatedRuntimeOptions<T, R>) {
  let epoch = 0, busy = false;
  let current: R | null = null;
  let controller: AbortController | null = null;
  const pending = (): never => {throw new ClientRuntimeError("auth_lifecycle_pending", "authentication or Runtime transition pending; explicit restart required");};
  function stop(): void {
    epoch++; controller?.abort(); controller = null;
    const previous = current; current = null; previous?.stop();
  }
  function check(version: number, signal: AbortSignal): void {if (version !== epoch || signal.aborted) pending();}
  async function start(): Promise<R> {
    if (busy) return pending();
    if (current?.isStopped) current = null;
    if (current !== null) return pending();
    busy = true;
    const version = ++epoch, abort = new AbortController(); controller = abort;
    let runtime: R | null = null;
    try {
      await options.auth.assertActive(); check(version, abort.signal);
      const boot = await options.bootstrap(abort.signal); check(version, abort.signal);
      await options.auth.assertActive(); check(version, abort.signal);
      runtime = options.create(boot); current = runtime;
      await options.mount(runtime, boot, abort.signal); check(version, abort.signal);
      if (runtime.isStopped) return pending();
      await options.auth.assertActive(); check(version, abort.signal);
      if (runtime.isStopped) return pending();
      return runtime;
    } catch (error) {
      if (current === runtime) current = null;
      // stop() already stopped an in-flight instance; do not release the same lease twice.
      if (runtime !== null && version === epoch) runtime.stop();
      abort.abort(); throw error;
    } finally {
      busy = false; if (controller === abort) controller = null;
    }
  }
  async function guarded<TValue>(call: () => Promise<TValue>): Promise<TValue> {
    stop(); return call(); // Stop synchronously BEFORE the first auth request, even if it fails.
  }
  return {
    start, stop,
    get runtime(): R | null {return current?.isStopped ? null : current;},
    refresh: (revision: number) => guarded(() => options.auth.refresh(revision)),
    retire: (revision: number) => guarded(() => options.auth.retire(revision)),
    inspect: (operation: string) => guarded(() => options.auth.inspect(operation)),
    async sync(): Promise<BFFAuthState> {
      try {const state = await options.auth.state(); if (state.status !== "active" || options.auth.pending() !== null) stop(); return state;}
      catch (error) {stop(); throw error;}
    },
  };
}
