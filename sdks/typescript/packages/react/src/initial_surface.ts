"use client";

import {useEffect,useLayoutEffect,useMemo,useRef} from "react";
import {ClientRuntimeError,MountedActionRegistry,prepareInitialClientSurface,type ZebraClientRuntime,type ClientActionHandler,type MountOptions} from "@zebra-agent/client-core";
import type {ZodType} from "zod";

type Prepared = ReturnType<typeof prepareInitialClientSurface>;
type Profile = Pick<MountOptions,"frontendAppId"|"profileRevision"|"profileDigest">;
/** Ephemeral page state, never authentication, retry authority or a durable operation journal. */
export interface ZebraInitialSurface {
  capture(): Prepared;
  adopt(runtime:ZebraClientRuntime, publicMetadata:unknown, profile:Profile):void;
}

class InitialSurface implements ZebraInitialSurface {
  private actions=new MountedActionRegistry();
  private readables=new Map<string,Record<string,unknown>>();
  private sealed:Prepared|null=null;
  private runtime:ZebraClientRuntime|null=null;
  private committed=false;
  private invalid=false;
  private generation=0;

  commit():()=>void {
    const generation=++this.generation;
    this.committed=true;
    return ()=>{
      this.committed=false;
      queueMicrotask(()=>{
        if(this.generation===generation){this.invalid=true;this.stop();}
      });
    };
  }
  private stop():void {const runtime=this.runtime;this.runtime=null;runtime?.stop();}
  private changed():void {if(this.sealed){this.invalid=true;this.stop();}}
  action(name:string,handler:ClientActionHandler):()=>void {
    try{this.actions.mount(name,handler);}catch(error){this.invalid=true;this.stop();throw error;}
    this.changed();
    return ()=>{this.actions.unmount(name);this.changed();};
  }
  readable(name:string,value:Record<string,unknown>):()=>void {
    if(this.readables.has(name)){this.invalid=true;this.stop();throw new ClientRuntimeError("initial_readable_conflict","duplicate initial Readable");}
    this.readables.set(name,value);this.changed();
    return ()=>{this.readables.delete(name);this.changed();};
  }
  update(name:string,value:Record<string,unknown>):void {
    const old=this.readables.get(name);
    if(old===undefined)throw new ClientRuntimeError("initial_readable_missing","initial Readable not mounted");
    if(JSON.stringify(old)!==JSON.stringify(value)){this.readables.set(name,value);this.changed();}
  }
  capture():Prepared {
    if(!this.committed||this.invalid||this.sealed)throw new ClientRuntimeError("initial_surface_not_ready","capture requires one live committed page and no prior capture");
    this.sealed=prepareInitialClientSurface(this.actions,Object.fromEntries(this.readables));
    return structuredClone(this.sealed);
  }
  adopt(runtime:ZebraClientRuntime,publicMetadata:unknown,profile:Profile):void {
    if(!this.committed||this.invalid||!this.sealed||this.runtime){if(runtime!==this.runtime)runtime.disconnect();throw new ClientRuntimeError("initial_surface_stale","original page capture is unavailable or changed");}
    try{
      for(const name of this.sealed.mountedActions)runtime.registry.mount(name,args=>this.actions.dispatch(name,args));
      for(const name of this.sealed.mountedReadables)runtime.mountReadable(name,this.sealed.input.state[name] as Record<string,unknown>);
      runtime.adoptInitialSurface(publicMetadata,{...profile,mountedActions:this.sealed.mountedActions,mountedReadables:this.sealed.mountedReadables});
      this.runtime=runtime;
    }catch(error){this.invalid=true;runtime.disconnect();throw error;}
  }
}
function initial(value:ZebraInitialSurface):InitialSurface {
  if(!(value instanceof InitialSurface))throw new ClientRuntimeError("initial_surface_invalid","use the Hook-owned initial Surface");
  return value;
}
/** No bootstrap or transport effect. Caller explicitly captures, dispatches once and observes originals. */
export function useZebraInitialSurface():ZebraInitialSurface {
  const value=useMemo(()=>new InitialSurface(),[]);
  useEffect(()=>value.commit(),[value]);
  return value;
}
export function useZebraInitialReadable(surface:ZebraInitialSurface,name:string,value:Record<string,unknown>):void {
  const target=initial(surface);
  const copy=prepareInitialClientSurface(new MountedActionRegistry(),{[name]:value}).input.state[name] as Record<string,unknown>;
  const serialized=JSON.stringify(copy);
  useLayoutEffect(()=>target.readable(name,copy),[target,name]);
  useLayoutEffect(()=>target.update(name,copy),[target,name,serialized]);
}
export function useZebraInitialAction<A extends Record<string,unknown>,R extends Record<string,unknown>>(
  surface:ZebraInitialSurface,name:string,options:{parameters:ZodType<A>;result:ZodType<R>;handler:(args:A)=>Promise<R>|R},
):void {
  const target=initial(surface), latest=useRef(options);
  useLayoutEffect(()=>{latest.current=options;},[options]);
  useLayoutEffect(()=>target.action(name,async args=>{
    const current=latest.current;
    return current.result.parseAsync(await current.handler(await current.parameters.parseAsync(args)));
  }),[target,name,options.parameters,options.result]);
}
