/**
 * Zebra React bindings: provider + standard hooks (ADR-CLIENT-01).
 *
 * Mounts register capabilities on mount and unregister on unmount;
 * Strict Mode double-invocations are guarded by the registry's
 * conflict semantics; the provider releases the client lease on
 * unmount. Handlers are typed functions — never serialized.
 */

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  ClientRuntimeError,
  ZebraClientRuntime,
  type ClientActionHandler,
} from "../../client-core/src/index.ts";
import type { RuntimeClientConfig } from "../../contracts/src/index.ts";

export interface ZebraAgentProviderProps {
  config: RuntimeClientConfig;
  frontendAppId: string;
  profileDigest: string;
  children: ReactNode;
}

interface ZebraAgentContextValue {
  runtime: ZebraClientRuntime;
  frontendAppId: string;
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
  useEffect(() => {
    setStatus("ready");
    return () => {
      // Provider unmount releases the client lease and stops execution.
      runtime.stop();
      setStatus("stopped");
    };
  }, [runtime]);
  const value: ZebraAgentContextValue = {
    runtime,
    frontendAppId: props.frontendAppId,
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

/** Register a semantic readable; updates produce a state revision. */
export function useZebraReadable(
  name: string,
  value: Record<string, unknown>,
): { revision: number } {
  const { runtime } = useZebra();
  const [revision, setRevision] = useState(runtime.uiRevision.current);
  const serialized = JSON.stringify(value);
  const reported = useRef(serialized);
  useEffect(() => {
    if (reported.current === serialized) return;
    reported.current = serialized;
    setRevision(runtime.uiRevision.bump());
  }, [serialized, runtime]);
  return { revision };
}

/** Register a typed action handler; unmount unregisters it. */
export function useZebraAction(
  name: string,
  handler: ClientActionHandler,
): { mounted: boolean } {
  const { runtime, frontendAppId, profileDigest } = useZebra();
  const handlerRef = useRef(handler);
  handlerRef.current = handler;
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const registered: ClientActionHandler = (args) =>
      handlerRef.current(args);
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
    void runtime.mount({
      frontendAppId,
      profileDigest,
      mountedActions: runtime.registry.names(),
    });
    return () => {
      runtime.registry.unmount(name);
      setMounted(false);
      void runtime.mount({
        frontendAppId,
        profileDigest,
        mountedActions: runtime.registry.names(),
      });
    };
  }, [name, runtime, frontendAppId, profileDigest]);
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
