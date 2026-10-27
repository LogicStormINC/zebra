"use client";

import {useMemo} from "react";
import {ClientRuntimeError,ZebraClientRuntime,validateSurfaceMetadata,type MountOptions} from "@zebra-agent/client-core";
import type {BffRuntimeClientConfig} from "@zebra-agent/contracts";
import {useZebraInitialSurface,type ZebraInitialSurface} from "./initial_surface.ts";

type Profile=Pick<MountOptions,"frontendAppId"|"profileRevision"|"profileDigest">;
export interface ZebraSurfaceRevisionBase {
  config:BffRuntimeClientConfig;
  publicMetadata:unknown;
  profile:Profile;
}
export interface ZebraSurfaceRevision {
  /** Register with the existing initial Hooks, then capture once after this page commits. */
  readonly surface:ZebraInitialSurface;
  /** Only after the trusted BFF confirms the original revision and its current mapping. No HTTP. */
  adopt(config:BffRuntimeClientConfig,publicMetadata:unknown,profile:Profile):ZebraClientRuntime;
}
function invalid():never {throw new ClientRuntimeError("surface_revision_invalid","revision must follow the exact prior public Surface on a new committed page");}
function previous(value:ZebraSurfaceRevisionBase) {
  const c=value.config,m=validateSurfaceMetadata(value.publicMetadata),p=value.profile;
  if([c.baseUrl,c.taskId,c.runId,c.clientSessionId,p.frontendAppId].some(v=>typeof v!=="string"||!v||v.length>512))invalid();
  if(c.mode!=="bff"||c.surfaceMetadataVersion!==1||c.clientStateVersion!==1||!c.controller||!m.controller||c.runBindingId!==m.binding_id||c.clientBindingDigest!==m.binding_digest||c.initialUiRevision!==m.ui_revision||
    !c.baseUrl||!c.taskId||!c.runId||!c.clientSessionId||!p.frontendAppId||!Number.isSafeInteger(p.profileRevision)||p.profileRevision<1||p.profileDigest!==m.profile_digest||m.allowed_actions.some(a=>c.actionContractDigests?.[a]!==m.action_contract_digests[a]))invalid();
  // Keep public coordinates only; do not capture transport functions, storage or mutable caller objects.
  return {baseUrl:c.baseUrl,taskId:c.taskId,runId:c.runId,clientSessionId:c.clientSessionId,commandRecoveryVersion:c.commandRecoveryVersion,metadata:m,profile:{frontendAppId:p.frontendAppId,profileRevision:p.profileRevision,profileDigest:p.profileDigest}};
}

/** Explicit new owner, not an automatic remount or an authentication/unknown-recovery service. */
export function useZebraSurfaceRevision(value:ZebraSurfaceRevisionBase):ZebraSurfaceRevision {
  const surface=useZebraInitialSurface(),base=useMemo(()=>previous(value),[]);
  if(JSON.stringify(previous(value))!==JSON.stringify(base))invalid();
  return useMemo(()=>({surface,adopt(config:BffRuntimeClientConfig,value:unknown,profile:Profile){
    const m=validateSurfaceMetadata(value),old=base.metadata;
    if(config.mode!=="bff"||config.baseUrl!==base.baseUrl||config.taskId!==base.taskId||config.runId!==base.runId||config.clientSessionId!==base.clientSessionId||config.runBindingId!==old.binding_id||
      config.surfaceMetadataVersion!==1||config.clientStateVersion!==1||config.commandRecoveryVersion!==base.commandRecoveryVersion||!config.controller||!m.controller||m.binding_id!==old.binding_id||m.profile_digest!==old.profile_digest||
      profile.frontendAppId!==base.profile.frontendAppId||profile.profileRevision!==base.profile.profileRevision||profile.profileDigest!==old.profile_digest||m.ui_revision!==old.ui_revision+1||m.binding_revision<=old.binding_revision||m.binding_digest===old.binding_digest||
      m.allowed_actions.some(a=>!old.allowed_actions.includes(a)||m.action_contract_digests[a]!==old.action_contract_digests[a]))invalid();
    const runtime=ZebraClientRuntime.fromConfig(config);
    surface.adopt(runtime,m,profile);
    return runtime;
  }}),[surface,base]);
}
