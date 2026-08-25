/**
 * Zebra React bindings: provider + standard hooks (ADR-CLIENT-01).
 *
 * Mounts register capabilities on mount and unregister on unmount;
 * Strict Mode double-invocations are guarded by the registry's
 * conflict semantics; the provider releases the client lease on
 * unmount. Handlers are typed functions — never serialized.
 */

import {
  createElement,
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { ZodType } from "zod";

import {
  ClientRuntimeError,
  ZebraClientRuntime,
  type ClientActionHandler,
} from "../../client-core/src/index.ts";
import type { RuntimeClientConfig } from "../../contracts/src/index.ts";

export interface ZebraAgentProviderProps {
  config: RuntimeClientConfig;
  frontendAppId: string;
  profileRevision: number;
  profileDigest: string;
  children: ReactNode;
}

interface ZebraAgentContextValue {
  runtime: ZebraClientRuntime;
  frontendAppId: string;
  profileRevision: number;
  profileDigest: string;
  status: "connecting" | "ready" | "stopped";
  mountedActions: string[];
  agentState: Record<string, unknown>;
  setAgentState: (next: Record<string, unknown>) => void;
}

const ZebraAgentContext = createContext<ZebraAgentContextValue | null>(null);

export function ZebraAgentProvider(props: ZebraAgentProviderProps) {
  const runtime = useMemo(
    () => ZebraClientRuntime.fromConfig(props.config),
    [props.config],
  );
  const [status, setStatus] = useState<"connecting" | "ready" | "stopped">(
    "connecting",
  );
  const [mountedActions, setMountedActions] = useState<string[]>([]);
  const [agentState, setAgentState] = useState<Record<string, unknown>>({});
  const lifecycleGeneration = useRef(0);
  useEffect(() => {
    lifecycleGeneration.current += 1;
    let active = true;
    void runtime.start().then(() => {
      if (active) setStatus("ready");
    });
    return () => {
      active = false;
      const cleanupGeneration = ++lifecycleGeneration.current;
      // React Strict Mode immediately re-runs effects; only a real unmount
      // survives this microtask and releases the controller lease.
      queueMicrotask(() => {
        if (lifecycleGeneration.current === cleanupGeneration) runtime.stop();
      });
    };
  }, [runtime]);
  const value: ZebraAgentContextValue = {
    runtime,
    frontendAppId: props.frontendAppId,
    profileRevision: props.profileRevision,
    profileDigest: props.profileDigest,
    status,
    mountedActions,
    agentState,
    setAgentState,
  };
  return createElement(
    ZebraAgentContext.Provider,
    { value },
    props.children,
  );
}

function useZebra(): ZebraAgentContextValue {
  const context = useContext(ZebraAgentContext);
  if (context === null) {
    throw new ClientRuntimeError(
      "missing_provider",
      "useZebra* hooks require <ZebraAgentProvider>",
    );
  }
  return context;
}

function synchronizeMount(
  runtime: ZebraClientRuntime,
  frontendAppId: string,
  profileRevision: number,
  profileDigest: string,
): Promise<void> {
  return runtime.scheduleMount({
    frontendAppId,
    profileRevision,
    profileDigest,
    mountedActions: runtime.registry.names(),
    mountedReadables: [...runtime.readableNames],
  });
}

function failClosedOnMount(runtime: ZebraClientRuntime, mount: Promise<void>): void {
  void mount.catch(() => runtime.stop());
}

/** Register a semantic readable; updates produce a state revision. */
export function useZebraReadable(
  name: string,
  value: Record<string, unknown>,
): { revision: number } {
  const { runtime, frontendAppId, profileRevision, profileDigest } = useZebra();
  const [revision, setRevision] = useState(runtime.uiRevision.current);
  const serialized = JSON.stringify(value);
  const reported = useRef(serialized);
  useEffect(() => {
    if (reported.current === serialized) return;
    reported.current = serialized;
    const mount = synchronizeMount(
      runtime,
      frontendAppId,
      profileRevision,
      profileDigest,
    );
    void mount
      .then(() => setRevision(runtime.uiRevision.current))
      .catch(() => runtime.stop());
  }, [serialized, runtime, frontendAppId, profileRevision, profileDigest]);
  useEffect(() => {
    runtime.mountReadable(name);
    const mount = synchronizeMount(runtime, frontendAppId, profileRevision, profileDigest);
    void mount
      .then(() => setRevision(runtime.uiRevision.current))
      .catch(() => runtime.stop());
    return () => {
      runtime.unmountReadable(name);
      failClosedOnMount(
        runtime,
        synchronizeMount(runtime, frontendAppId, profileRevision, profileDigest),
      );
    };
  }, [name, runtime, frontendAppId, profileRevision, profileDigest]);
  return { revision };
}

/** Register a typed action handler; unmount unregisters it. */
export interface ZebraActionOptions<
  TArgs extends Record<string, unknown>,
  TResult extends Record<string, unknown>,
> {
  parameters: ZodType<TArgs>;
  result: ZodType<TResult>;
  handler: (args: TArgs) => Promise<TResult> | TResult;
}

export function useZebraAction<
  TArgs extends Record<string, unknown>,
  TResult extends Record<string, unknown>,
>(
  name: string,
  options: ZebraActionOptions<TArgs, TResult>,
): { mounted: boolean } {
  const { runtime, frontendAppId, profileRevision, profileDigest } = useZebra();
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const registered: ClientActionHandler = async (args) => {
      const parsed = await optionsRef.current.parameters.parseAsync(args);
      const result = await optionsRef.current.handler(parsed);
      return optionsRef.current.result.parseAsync(result);
    };
    try {
      runtime.registry.mount(name, registered);
    } catch (error) {
      if (
        error instanceof ClientRuntimeError &&
        error.code === "action_already_mounted"
      ) {
        throw new ClientRuntimeError(
          "action_conflict",
          `multiple components registered the same action ${name}`,
        );
      }
      throw error;
    }
    setMounted(true);
    failClosedOnMount(
      runtime,
      synchronizeMount(runtime, frontendAppId, profileRevision, profileDigest),
    );
    return () => {
      runtime.registry.unmount(name);
      setMounted(false);
      failClosedOnMount(
        runtime,
        synchronizeMount(runtime, frontendAppId, profileRevision, profileDigest),
      );
    };
  }, [name, runtime, frontendAppId, profileRevision, profileDigest]);
  return { mounted };
}

export function useZebraClientStatus(): "connecting" | "ready" | "stopped" {
  return useZebra().status;
}

export function useZebraTask(): { agentState: Record<string, unknown> } {
  const { agentState } = useZebra();
  return { agentState };
}

export function useZebraAgentState(): [
  Record<string, unknown>,
  (next: Record<string, unknown>) => void,
] {
  const { agentState, setAgentState } = useZebra();
  return [agentState, setAgentState];
}
