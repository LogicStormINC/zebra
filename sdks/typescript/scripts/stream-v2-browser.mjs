/** SDK parser/reducer + controlled React over a disposable loopback fixture. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, mkdtemp, readFile, rm } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
const sdk = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);
const { build } = createRequire(require.resolve("bunchee"))("esbuild");
const scratch = await mkdtemp(join(tmpdir(), "zebra-stream-v2-"));
const artifacts = join(resolve(sdk, "../.."), ".artifacts", "stream-client");
await mkdir(artifacts, { recursive: true });
const entry = `
import React from "react";
import {createRoot} from "react-dom/client";
import {AgentMessageList} from "${join(sdk,"packages/react/src/components/agent-message-list.tsx")}";
import {ConversationStreamReducer} from "${join(sdk,"packages/client-core/src/conversation_stream.ts")}";
import {consumeClientEffectStream} from "${join(sdk,"packages/client-core/src/sse_stream.ts")}";
const reducer = new ConversationStreamReducer(), root=createRoot(document.getElementById("root"));
window.effects=[]; window.abort=new AbortController();
consumeClientEffectStream({fetchImpl:(url,init)=>fetch(url,init),streamUrl:"/stream",headers:()=>({}),
stopped:()=>false,signal:window.abort.signal,streamVersion:2,initialEventId:sessionStorage.getItem("cursor"),
onCursor:cursor=>{if(cursor)sessionStorage.setItem("cursor",cursor)},
onObservation:async event=>{reducer.observe(event);root.render(React.createElement(AgentMessageList,{messages:reducer.snapshot(),labels:{draft:"临时草稿"}}))},
onCursorRecovered:async()=>{window.recovered=true},
onEffect:async effect=>{window.effects.push(effect.effect_id);await fetch("/receipt",{method:"POST",body:effect.effect_id})}}).catch(error=>{window.streamFailure=String(error);window.abort.abort()});`;
await build({stdin:{contents:entry,resolveDir:sdk,loader:"tsx"},bundle:true,platform:"browser",format:"iife",outfile:join(scratch,"fixture.js"),nodePaths:[join(sdk,"packages/react/node_modules")]});
const javascript=await readFile(join(scratch,"fixture.js"));
const wire=(id,name,value)=>`id: ${id}\ndata: ${JSON.stringify({type:"CUSTOM",name,value})}\n\n`;
const replacement=(content)=>wire("replace","zebra.message_replace",{message_id:"message:call",model_call_id:"call",chunk_index:0,content,last:true});
const commit=()=>wire("commit","zebra.answer_committed",{model_call_id:"call",replacement_committed:true});
const draft=(id,generation,offset,content,index=0,last=true)=>wire(last?"whole-wire":"partial-wire","zebra.stream.draft",{message_id:id,generation_id:generation,offset,content_delta:content,chunk_index:index,last});
const effect=id=>({effect_id:id,status:"pending",execution_location:"client"});
const effects=id=>`id: effect-${id}\ndata: ${JSON.stringify({type:"STATE_DELTA",delta:[{op:"add",value:effect(id)},...(id==="historic"?[{op:"remove",path:"/effects/historic"}]:[])]})}\n\n`;
let connection, committed=false, partial=false, connections=0;
const receipts=[],requests=[];
const server=createServer(async(request,response)=>{
 const url=new URL(request.url,"http://fixture.local");
 if(url.pathname==="/"){response.setHeader("Content-Type","text/html; charset=utf-8");return response.end('<meta charset="UTF-8"><div id="root"></div><script src="/fixture.js"></script>')}
 if(url.pathname==="/fixture.js"){response.setHeader("Content-Type","text/javascript");return response.end(javascript)}
 if(url.pathname==="/receipt"){let body="";for await(const chunk of request)body+=chunk;receipts.push(body);return response.end("accepted")}
 if(url.pathname==="/stream"){
  connections++; requests.push({recovery:url.searchParams.get("recovery"),cursor:request.headers["last-event-id"]});connection=response;
  response.writeHead(200,{"Content-Type":"text/event-stream","Cache-Control":"no-cache"});
  if(partial&&request.headers["last-event-id"]==="partial-wire"){partial=false;response.write(draft("message:preview","preview",0,"完整",1));return}
  response.write(wire("start","zebra.stream.recovery_start",{}));
  if(committed)response.write(effects("historic")+replacement("最终确认正文")+commit());
  response.write(wire("caught-up","zebra.stream.recovery_complete",{}));
  if(!committed)response.write(draft("message:call","gen",0,"错误候选正文"));return;
 }
 if(url.pathname==="/advance/replace")connection.write(replacement("校验后的候选正文")+draft("message:call","gen",1,"不应追加")+wire("reset","zebra.stream.reset",{}));
 else if(url.pathname==="/advance/commit"){committed=true;connection.write(replacement("最终确认正文")+commit())}
 else if(url.pathname==="/advance/partial"){partial=true;connection.end(draft("message:preview","preview",0,"新草稿",0,false))}
 else if(url.pathname==="/advance/tool")connection.write(effects("current"));
 else response.statusCode=404;
 response.end("ok");
});
await new Promise(resolveListen=>server.listen(0,"127.0.0.1",resolveListen));
const url=`http://127.0.0.1:${server.address().port}`;
let browser;
try{
 browser=await chromium.launch({headless:true});const page=await browser.newPage();const errors=[];
 page.on("pageerror",error=>{errors.push(error.message);console.error("browser error",error.message)});await page.goto(url);
 await page.getByText("错误候选正文",{exact:true}).waitFor();assert.equal(await page.getByText("临时草稿",{exact:true}).count(),1);
 await page.screenshot({path:join(artifacts,"draft.png")});
 await page.evaluate(()=>fetch("/advance/replace"));await page.getByText("校验后的候选正文",{exact:true}).waitFor();
 assert.equal(await page.getByText("错误候选正文",{exact:true}).count(),0);assert.equal(await page.getByText("不应追加",{exact:true}).count(),0);assert.equal(await page.getByText("临时草稿",{exact:true}).count(),1);
 await page.evaluate(()=>fetch("/advance/commit"));await page.getByText("最终确认正文",{exact:true}).waitFor();assert.equal(await page.getByText("临时草稿",{exact:true}).count(),0);
 await page.reload();await page.getByText("最终确认正文",{exact:true}).waitFor();assert.equal(await page.evaluate(()=>window.effects.length),0);
 await page.evaluate(()=>fetch("/advance/partial"));await page.getByText("新草稿完整",{exact:true}).waitFor();assert.equal(requests.at(-1).cursor,"partial-wire");
 await page.evaluate(()=>fetch("/advance/tool"));await page.waitForFunction(()=>window.effects.length===1);assert.deepEqual(await page.evaluate(()=>window.effects),["current"]);
 assert.deepEqual(receipts,["current"]);assert.deepEqual(errors,[]);assert.equal(await page.evaluate(()=>window.streamFailure),undefined);assert.ok(connections>=3);await page.screenshot({path:join(artifacts,"recovered.png")});
 console.log(JSON.stringify({browser:"Chromium",draft_replace_commit_refresh_partial_resume_tool:"passed",connections,receipts:receipts.length,errors:errors.length}));
}finally{await browser?.close();server.closeAllConnections();await new Promise(resolveClose=>server.close(resolveClose));await rm(scratch,{recursive:true,force:true})}
