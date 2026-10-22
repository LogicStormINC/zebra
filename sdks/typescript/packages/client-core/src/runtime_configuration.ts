import type { RuntimeBrowserConfig } from "@zebra-agent/contracts";
import { streamObserverOptions, type StreamObserverOptions } from "./conversation_stream.ts";
import { ClientRuntimeError } from "./errors.ts";
import { createBffFetch } from "./bff_transport.ts";
import { browserSessionStorage } from "./runtime_state.ts";
import type { BrowserRuntimeDependencies } from "./index.ts";

const uuid = (value: unknown): value is string => typeof value === "string" &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
const digest = (value: unknown): value is string => typeof value === "string" && value.length === 64 && /^[0-9a-f]{64}$/.test(value);

export function runtimeDependencies(config: RuntimeBrowserConfig & StreamObserverOptions): BrowserRuntimeDependencies {
  if (config.mode !== undefined && config.mode !== "legacy" && config.mode !== "bff") {
    throw new ClientRuntimeError("invalid_config", "unknown runtime transport mode");
  }
  if (config.mode === "bff") {
    const allowed = ["mode", "baseUrl", "clientSessionId", "controller", "taskId", "runId", "runBindingId",
      "clientBindingDigest", "actionContractDigests", "initialUiRevision", "storage", "fetchImpl", "surfaceMetadataVersion"];
    if (Object.keys(config).some(key => !allowed.includes(key))) {
      throw new ClientRuntimeError("invalid_bff_config", "BFF mode forbids native secrets and streaming configuration");
    }
    if (typeof config.controller !== "boolean" || !uuid(config.clientSessionId)) {
      throw new ClientRuntimeError("invalid_bff_config", "BFF mode requires a public session identifier and role hint");
    }
    if (config.surfaceMetadataVersion !== undefined && config.surfaceMetadataVersion !== 1 ||
      config.surfaceMetadataVersion === 1 && (!Number.isSafeInteger(config.initialUiRevision) || Number(config.initialUiRevision) < 0)) {
      throw new ClientRuntimeError("invalid_bff_config", "synchronized surface requires version1 and an actual initial UI revision");
    }
    const actions = config.actionContractDigests;
    if ((config.controller || config.surfaceMetadataVersion === 1) && (!uuid(config.taskId) || typeof config.runId !== "string" ||
      config.runId.length < 1 || config.runId.length > 128 || !uuid(config.runBindingId) ||
      !digest(config.clientBindingDigest) || !actions || typeof actions !== "object" || Array.isArray(actions) ||
      Object.keys(actions).length > 128 || Object.entries(actions).some(([name, value]) => !name || name.length > 128 || !digest(value)))) {
      throw new ClientRuntimeError("invalid_bff_config", "controller metadata is incomplete or malformed");
    }
    return {
      mode: "bff", controller: config.controller, surfaceMetadataVersion: config.surfaceMetadataVersion,
      fetchImpl: createBffFetch(config.baseUrl, config.clientSessionId, config.fetchImpl ?? ((input, init) => globalThis.fetch(input, init))),
      baseUrl: config.baseUrl, clientSessionId: config.clientSessionId,
      taskId: config.taskId, runId: config.runId, runBindingId: config.runBindingId,
      clientBindingDigest: config.clientBindingDigest, actionContractDigests: config.actionContractDigests,
      initialUiRevision: config.initialUiRevision, storage: config.storage ?? browserSessionStorage(),
    };
  }
  const sessionSecret = config.sessionCredential.slice(config.clientSessionId.length + 1);
  if (
    !config.sessionCredential.startsWith(`${config.clientSessionId}:`) ||
    sessionSecret.length < 16 ||
    /\s/.test(sessionSecret)
  ) {
    throw new ClientRuntimeError(
      "invalid_credential",
      "session credential must be '<session-id>:<session-secret>'",
    );
  }
  const controllerCoordinates = [
    config.taskId,
    config.runId,
    config.runBindingId,
    config.clientBindingDigest,
    config.actionContractDigests,
  ];
  if (
    config.controllerFenceToken !== undefined &&
    (
      config.controllerFenceToken.length < 16 ||
      /\s/.test(config.controllerFenceToken) ||
      controllerCoordinates.some(
        (value) =>
          value === undefined ||
          (typeof value === "string" && value.trim() === ""),
      ) ||
      !/^[0-9a-f]{64}$/.test(config.clientBindingDigest ?? "") ||
      Object.values(config.actionContractDigests ?? {}).some(
        (digest) => !/^[0-9a-f]{64}$/.test(digest),
      )
    )
  ) {
    throw new ClientRuntimeError(
      "invalid_controller_binding",
      "controller fence requires binding coordinates and action digests",
    );
  }
  if (
    config.streamUrl !== undefined &&
    new URL(config.streamUrl, config.baseUrl).origin !== new URL(config.baseUrl).origin
  ) {
    throw new ClientRuntimeError(
      "cross_origin_stream",
      "the AG-UI stream must share the Host BFF origin",
    );
  }
  return {
    // Preserve window.fetch's receiver; an object-field call fails in Chromium.
    fetchImpl: config.fetchImpl ?? ((input, init) => globalThis.fetch(input, init)),
    baseUrl: config.baseUrl,
    clientSessionId: config.clientSessionId,
    sessionCredential: config.sessionCredential,
    controllerFenceToken: config.controllerFenceToken,
    taskId: config.taskId,
    runId: config.runId,
    runBindingId: config.runBindingId,
    clientBindingDigest: config.clientBindingDigest,
    actionContractDigests: config.actionContractDigests,
    initialUiRevision: config.initialUiRevision,
    streamUrl: config.streamUrl,
    ...streamObserverOptions(config),
    storage: config.storage ?? browserSessionStorage(),
  };
}
