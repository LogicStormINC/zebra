import {MountedActionRegistry} from "./action_registry.ts";
import {copyReadableJson} from './readable_commands.ts';
import {ClientRuntimeError} from './errors.ts';
import {validateSurfaceMetadata} from './surface_metadata.ts';
import type {BrowserRuntimeDependencies, MountOptions} from './index.ts';

/** Capture BEFORE Task dispatch; handlers stay in the browser. No network or credentials. */
export function prepareInitialClientSurface(registry: MountedActionRegistry, readables: Readonly<Record<string,Record<string,unknown>>>) {
  if(!(registry instanceof MountedActionRegistry))throw new ClientRuntimeError("initial_surface_invalid","registered UI handlers required");
  const actions=registry.names();
  const valid=(name:string)=>/^[a-z][a-z0-9]*(-[a-z0-9]+)*(\.[a-z0-9-]+)+$/.test(name)&&name.length<=64;
  const names=Object.keys(readables);
  if(actions.length>128||names.length>128||new Set(actions).size!==actions.length||[...actions,...names].some(n=>!valid(n))) throw new ClientRuntimeError('initial_surface_invalid','invalid initial capability names');
  const state=copyReadableJson(readables);
  // Admission canonical JSON is intentionally integer-only; ordinary commands keep their existing contract.
  const portable=(v:unknown):boolean=> typeof v==='number'?Number.isSafeInteger(v):v!==null&&typeof v==='object'?Object.values(v).every(portable):true;
  if(!portable(state))throw new ClientRuntimeError('initial_surface_invalid','initial state requires portable integer JSON');
  return {mountedActions:[...actions],mountedReadables:names,input:{state}};
}

export function initialSurfaceMetadata(value:unknown,options:MountOptions,deps:BrowserRuntimeDependencies,revision:number,actions:readonly string[],readables:readonly string[]) {
  const m=validateSurfaceMetadata(value);
  const same=(a:readonly string[],b:readonly string[])=>a.length===b.length&&a.every(n=>b.includes(n));
  if(deps.mode!=='bff'||deps.surfaceMetadataVersion!==1||m.ui_revision!==revision||m.profile_digest!==options.profileDigest||m.binding_id!==deps.runBindingId||m.binding_digest!==deps.clientBindingDigest||m.controller!==deps.controller||
    !same(actions,options.mountedActions)||!same(readables,options.mountedReadables??[])||m.allowed_actions.some(a=>!actions.includes(a))||Object.entries(m.action_contract_digests).some(([a,h])=>deps.actionContractDigests?.[a]!==h)) throw new ClientRuntimeError('initial_surface_invalid','initial native binding mismatch');
  return m;
}
