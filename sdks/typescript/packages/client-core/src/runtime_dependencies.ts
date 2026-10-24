import type {StreamObserverOptions} from "./conversation_stream.ts";

export interface MountOptions {
  frontendAppId: string;
  profileRevision: number;
  profileDigest: string;
  mountedActions: readonly string[];
  mountedReadables?: readonly string[];
}
export interface ClientRuntimeDependencies extends StreamObserverOptions {
  fetchImpl: typeof fetch;
  baseUrl: string;
  clientSessionId: string;
  sessionCredential: string;
  mode?: "legacy" | undefined;
  controllerFenceToken?: string | undefined;
  taskId?: string | undefined;
  runId?: string | undefined;
  runBindingId?: string | undefined;
  clientBindingDigest?: string | undefined;
  actionContractDigests?: Readonly<Record<string, string>> | undefined;
  initialUiRevision?: number | undefined;
  streamUrl?: string | undefined;
  storage?: Storage | undefined;
}
/** Preserve the original required-secret DI type for existing server/legacy consumers. */
export type BrowserRuntimeDependencies = ClientRuntimeDependencies | (
  Omit<ClientRuntimeDependencies, "mode" | "sessionCredential" | "controllerFenceToken" | "streamUrl"> & {
    mode: "bff";
    controller: boolean;
    surfaceMetadataVersion?: 1 | undefined;
    clientStateVersion?: 1 | undefined;
    commandRecoveryVersion?: 1 | undefined;
    sessionCredential?: never;
    controllerFenceToken?: never;
    streamUrl?: never;
  }
);
