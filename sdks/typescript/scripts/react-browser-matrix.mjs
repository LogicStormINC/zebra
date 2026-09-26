import { createServer } from "node:http";
import { mkdtemp, mkdir, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { createServer as createNetServer } from "node:net";

import { chromium, webkit } from "@playwright/test";

const sdkRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const workspace = await mkdtemp(join(tmpdir(), "zebra-react-browser-"));
const packDirectory = join(workspace, "tarballs");
let nextProcess;

try {
  await mkdir(packDirectory, { recursive: true });
  await run("pnpm", ["build"], sdkRoot);
  const tarballs = await packPackages();
  for (const [browserName, browserType] of [["Chromium", chromium], ["WebKit", webkit]]) {
    const browser = await browserType.launch({ headless: true });
    try {
      await verifyViteInteractions(browser, tarballs, browserName);
      if (browserName === "Chromium") await verifyNextHydration(browser, tarballs);
    } finally {
      await browser.close();
    }
  }
  console.log("React browser matrix passed: Chromium/WebKit interactions and Next hydration");
} finally {
  nextProcess?.kill("SIGTERM");
  await rm(workspace, { force: true, recursive: true });
}

async function packPackages() {
  const packages = {
    "@zebra-agent/contracts": "contracts",
    "@zebra-agent/ui-contracts": "ui-contracts",
    "@zebra-agent/client-core": "client-core",
    "@zebra-agent/react": "react",
  };
  const tarballs = {};
  for (const [name, directory] of Object.entries(packages)) {
    const before = new Set(await readdir(packDirectory));
    await run("pnpm", ["pack", "--pack-destination", packDirectory], join(sdkRoot, "packages", directory));
    const created = (await readdir(packDirectory)).filter((entry) => entry.endsWith(".tgz") && !before.has(entry));
    if (created.length !== 1) throw new Error(`${name}: expected one tarball`);
    tarballs[name] = `file:${join(packDirectory, created[0])}`;
  }
  return tarballs;
}

async function verifyViteInteractions(browser, tarballs, browserName) {
  const root = join(workspace, "vite-browser");
  await writeFiles(root, {
    "package.json": packageJson("zebra-browser-vite", tarballs, { vite: "6.4.3" }, "vite build"),
    "index.html": '<style>html,body,#root{height:100%;margin:0}</style><div id="root"></div><script type="module" src="/src/main.tsx"></script>',
    "src/main.tsx": viteFixtureSource(),
    "tsconfig.json": JSON.stringify({ compilerOptions: { jsx: "react-jsx", lib: ["ES2022", "DOM"], module: "ESNext", moduleResolution: "Bundler", noEmit: true, strict: true, target: "ES2022" }, include: ["src"] }, null, 2),
  });
  await installAndBuild(root);
  const server = await serveDirectory(join(root, "dist"));
  try {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
    const errors = collectBrowserErrors(page);
    await page.goto(server.url);
    await page.setViewportSize({ width: 1280, height: 900 });
    const emptyComposerWidth = await page.locator(".zebra-agent-chat__composer").evaluate((node) => Math.round(node.getBoundingClientRect().width));
    if (emptyComposerWidth !== 672) throw new Error(`${browserName}: centered draft composer expected 672px, received ${emptyComposerWidth}px`);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator("textarea").fill("中文草稿");
    await page.locator('input[type="file"]').setInputFiles({ name: "资料.txt", mimeType: "text/plain", buffer: Buffer.from("evidence") });
    await page.locator("textarea").focus();
    await page.locator("#activate").evaluate((node) => node.click());
    if (await page.locator("textarea").inputValue() !== "中文草稿") throw new Error("draft was lost during lifecycle transition");
    if (!(await page.locator("textarea").evaluate((node) => node === document.activeElement))) throw new Error("composer focus was lost");
    if (!(await page.locator("details").evaluate((node) => node.open))) throw new Error("running activity did not expand");
    const customTheme = await page.evaluate(() => ({
      chatBackground: getComputedStyle(document.querySelector(".zebra-agent-chat")).backgroundColor,
      composerInputToken: getComputedStyle(document.querySelector(".zebra-agent-composer")).getPropertyValue("--zebra-agent-input").trim(),
    }));
    if (customTheme.chatBackground !== "rgb(16, 24, 32)") throw new Error(`${browserName}: custom chat surface token was not applied`);
    if (customTheme.composerInputToken !== "#123456") throw new Error(`${browserName}: nested composer did not inherit custom input token`);
    await assertComposerDocked(page, browserName, "short active mobile conversation");
    const expandUserMessage = page.getByRole("button", { name: "Expand message" });
    await expandUserMessage.waitFor();
    const collapsedHeight = await page.locator(".zebra-agent-user-input__content").evaluate((node) => getComputedStyle(node).maxHeight);
    if (collapsedHeight !== "120px") throw new Error(`${browserName}: user message collapsed height expected 120px, received ${collapsedHeight}`);
    await expandUserMessage.click();
    await page.getByRole("button", { name: "Collapse message" }).waitFor();
    await assertComposerDocked(page, browserName, "expanded mobile conversation");
    const mobileGeometry = await readConversationGeometry(page);
    assertGeometry(browserName, mobileGeometry, { turnPaddingTop: "40px", contentWidth: 390 });
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.waitForTimeout(200);
    const desktopGeometry = await readConversationGeometry(page);
    assertGeometry(browserName, desktopGeometry, { turnPaddingTop: "56px", contentWidth: 896 });
    await assertComposerDocked(page, browserName, "desktop conversation");
    await page.setViewportSize({ width: 1800, height: 900 });
    await page.waitForTimeout(200);
    const wideGeometry = await readConversationGeometry(page);
    assertGeometry(browserName, wideGeometry, { turnPaddingTop: "56px", contentWidth: 1152 });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator("#complete").click();
    await page.waitForFunction(() => !document.querySelector("details")?.open);
    const terminalSummaryBorder = await page.locator(".zebra-agent-activity--terminal summary").evaluate((node) => getComputedStyle(node).borderBottomWidth);
    if (terminalSummaryBorder !== "1px") throw new Error(`${browserName}: completed history divider expected 1px, received ${terminalSummaryBorder}`);
    const terminalSummaryIcon = await page.locator(".zebra-agent-activity--terminal .zebra-agent-activity__summary-icon").evaluate((node) => getComputedStyle(node).display);
    if (terminalSummaryIcon !== "none") throw new Error(`${browserName}: completed history icon must be hidden, received ${terminalSummaryIcon}`);
    await page.locator("#disconnected").click();
    await page.getByRole("button", { name: "Reconnect" }).click();
    await page.locator("#paused").click();
    await page.getByRole("button", { name: "Continue task" }).click();
    await page.locator("#failed").click();
    await page.getByRole("button", { name: "Retry original request" }).click();
    await page.locator("textarea").evaluate((node) => node.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Enter", isComposing: true })));
    if (await page.locator("#submits").textContent() !== "0") throw new Error("IME Enter submitted the draft");
    await page.locator("textarea").evaluate((node) => node.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Enter", keyCode: 229 })));
    if (await page.locator("#submits").textContent() !== "0") throw new Error("Safari IME keyCode 229 submitted the draft");
    await page.locator("textarea").press("Enter");
    if (await page.locator("#submits").textContent() !== "1") throw new Error("Enter did not submit the draft");
    await page.locator("#burst").click();
    await page.getByText(/Long output 29/).waitFor();
    const viewport = page.locator(".zebra-agent-chat__viewport");
    await viewport.evaluate((node) => { node.scrollTop = 120; node.dispatchEvent(new Event("scroll")); });
    const beforeSwitch = await viewport.evaluate((node) => node.scrollTop);
    await page.locator("#thread-b").click();
    await page.waitForFunction(() => document.querySelector("#scroll-key")?.textContent === "thread-b");
    await page.locator("#thread-a").click();
    await page.waitForFunction(() => document.querySelector("#scroll-key")?.textContent === "thread-a");
    await page.waitForTimeout(100);
    const afterSwitch = await viewport.evaluate((node) => node.scrollTop);
    if (Math.abs(afterSwitch - beforeSwitch) > 2) throw new Error(`conversation scroll position was not restored: ${beforeSwitch} -> ${afterSwitch}`);
    await viewport.evaluate((node) => { node.scrollTop = 0; node.dispatchEvent(new Event("scroll")); });
    await page.locator("#append").click();
    await page.getByRole("button", { name: "View latest output" }).click();
    await page.waitForFunction(() => {
      const node = document.querySelector(".zebra-agent-chat__viewport");
      return node && node.scrollHeight - node.scrollTop - node.clientHeight < 20;
    });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    if (overflow) throw new Error("narrow viewport has horizontal overflow");
    await page.locator("textarea").focus();
    await page.keyboard.press(browserName === "WebKit" ? "Alt+Tab" : "Tab");
    if (!(await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.matches(".zebra-agent-chat button,.zebra-agent-chat select,.zebra-agent-chat input")))) {
      throw new Error("keyboard navigation did not reach an interactive control");
    }
    const undersizedTargets = await page.locator(".zebra-agent-chat button:not([disabled])").evaluateAll((nodes) => nodes.filter((node) => {
      const rect = node.getBoundingClientRect();
      return rect.width < 24 || rect.height < 24;
    }).map((node) => `${node.textContent?.trim() || node.getAttribute("aria-label")}:${Math.round(node.getBoundingClientRect().width)}x${Math.round(node.getBoundingClientRect().height)}`));
    if (undersizedTargets.length) throw new Error(`${browserName}: undersized interaction targets: ${undersizedTargets.join(", ")}`);
    if (errors.length) throw new Error(`${browserName} Vite browser errors: ${errors.join(" | ")}`);
    await page.close();
  } finally {
    await server.close();
  }
}

async function readConversationGeometry(page) {
  return page.evaluate(() => {
    const turn = document.querySelector(".zebra-agent-turn");
    const content = document.querySelector(".zebra-agent-chat__content");
    const bubble = document.querySelector(".zebra-agent-message--user article");
    const activity = document.querySelector(".zebra-agent-activity summary");
    const activityBody = document.querySelector(".zebra-agent-activity ol");
    const composer = document.querySelector(".zebra-agent-composer");
    if (!turn || !content || !bubble || !activity || !activityBody || !composer) throw new Error("conversation geometry fixture missing");
    const turnStyle = getComputedStyle(turn);
    const bubbleStyle = getComputedStyle(bubble);
    return {
      activityBodyBorderLeft: getComputedStyle(activityBody).borderLeftWidth,
      activityFontSize: getComputedStyle(activity).fontSize,
      bubblePadding: `${bubbleStyle.paddingTop} ${bubbleStyle.paddingRight}`,
      bubbleRadius: bubbleStyle.borderRadius,
      composerRadius: getComputedStyle(composer).borderRadius,
      contentWidth: Math.round(content.getBoundingClientRect().width),
      turnGap: turnStyle.gap,
      turnPaddingTop: turnStyle.paddingTop,
    };
  });
}

function assertGeometry(browserName, actual, expected) {
  const stable = {
    activityBodyBorderLeft: "0px",
    activityFontSize: "14px",
    bubblePadding: "12px 16px",
    bubbleRadius: "8px",
    composerRadius: "16px",
    turnGap: "20px",
    ...expected,
  };
  for (const [key, value] of Object.entries(stable)) {
    if (actual[key] !== value) throw new Error(`${browserName}: ${key} expected ${value}, received ${actual[key]}`);
  }
}

async function assertComposerDocked(page, browserName, context) {
  const offset = await page.evaluate(() => {
    const chat = document.querySelector(".zebra-agent-chat");
    const viewport = document.querySelector(".zebra-agent-chat__viewport");
    const composer = document.querySelector(".zebra-agent-chat__composer");
    if (!chat || !viewport || !composer) throw new Error("composer docking fixture missing");
    return {
      composerToViewport: Math.round(viewport.getBoundingClientRect().bottom - composer.getBoundingClientRect().bottom),
      viewportToChat: Math.round(chat.getBoundingClientRect().bottom - viewport.getBoundingClientRect().bottom),
    };
  });
  if (Math.abs(offset.composerToViewport) > 1) throw new Error(`${browserName}: ${context} composer-to-viewport offset expected 0px, received ${offset.composerToViewport}px`);
  if (Math.abs(offset.viewportToChat) > 1) throw new Error(`${browserName}: ${context} viewport-to-chat offset expected 0px, received ${offset.viewportToChat}px`);
}

async function verifyNextHydration(browser, tarballs) {
  const root = join(workspace, "next-browser");
  await writeFiles(root, {
    "package.json": packageJson("zebra-browser-next", tarballs, { next: "15.5.18" }, "next build", "next start"),
    "app/layout.tsx": 'import "@zebra-agent/react/styles.css"; export default function Layout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>}',
    "app/page.tsx": 'import { AgentRunStatus } from "@zebra-agent/react"; export default function Page(){return <AgentRunStatus state={{phase:"terminal",outcome:"completed",availableActions:[]}}/>}',
    "next-env.d.ts": '/// <reference types="next" />',
    "tsconfig.json": JSON.stringify({ compilerOptions: { esModuleInterop: true, jsx: "preserve", lib: ["DOM", "ES2022"], module: "ESNext", moduleResolution: "Bundler", noEmit: true, strict: true, target: "ES2022" }, include: ["next-env.d.ts", ".next/types/**/*.ts", "**/*.ts", "**/*.tsx"] }, null, 2),
  });
  await installAndBuild(root);
  const port = await freePort();
  let serverOutput = "";
  nextProcess = spawn("pnpm", ["exec", "next", "start", "-H", "127.0.0.1", "-p", String(port)], { cwd: root, env: process.env, stdio: ["ignore", "pipe", "pipe"] });
  nextProcess.stdout.on("data", (chunk) => { serverOutput += chunk; });
  nextProcess.stderr.on("data", (chunk) => { serverOutput += chunk; });
  await waitForUrl(`http://127.0.0.1:${port}`, () => serverOutput);
  const page = await browser.newPage();
  const errors = collectBrowserErrors(page);
  await page.goto(`http://127.0.0.1:${port}`);
  await page.getByText("Completed", { exact: true }).waitFor();
  if (errors.length) throw new Error(`Next hydration errors: ${errors.join(" | ")}`);
  await page.close();
  nextProcess.kill("SIGTERM");
  nextProcess = undefined;
}

function packageJson(name, tarballs, framework, build, start) {
  return JSON.stringify({ name, private: true, scripts: { build, ...(start ? { start } : {}) }, dependencies: { ...tarballs, ...framework, react: "19.2.8", "react-dom": "19.2.8" }, devDependencies: { "@types/node": "22.20.4", "@types/react": "19.2.18", "@types/react-dom": "19.2.5", typescript: "5.9.3" }, pnpm: { overrides: tarballs } }, null, 2);
}

function viteFixtureSource() {
  return `
import { createElement, useState } from "react";
import { createRoot } from "react-dom/client";
import { AgentChat, AgentComposer } from "@zebra-agent/react";
import "@zebra-agent/react/styles.css";

function App(){
  const [phase,setPhase]=useState("idle"); const [value,setValue]=useState(""); const [files,setFiles]=useState([]); const [submits,setSubmits]=useState(0); const [actions,setActions]=useState([]); const [turns,setTurns]=useState([]); const [scrollKey,setScrollKey]=useState("thread-a");
  const state=phase==="running"?{phase:"running",availableActions:[]}:phase==="completed"?{phase:"terminal",outcome:"completed",availableActions:[]}:phase==="disconnected"?{phase:"disconnected",availableActions:["reconnect"]}:phase==="paused"?{phase:"paused",availableActions:["resume"]}:phase==="failed"?{phase:"terminal",outcome:"failed",availableActions:["retry"]}:{phase:"idle",availableActions:[]};
  const composer=createElement(AgentComposer,{attachments:files,busy:phase==="running",capabilityOptions:[],capabilityValue:"general",canContinue:false,disabled:false,metrics:{cacheHitRate:null,contextLimit:null,contextPercent:null,contextTokens:null},modelOptions:[],modelValue:"default",onCapabilityChange:()=>{},onContinue:()=>{},onFilesSelected:(list)=>setFiles([...list].map((file,index)=>({id:String(index),isImage:false,name:file.name}))),onModelChange:()=>{},onPause:()=>{},onReasoningChange:()=>{},onRemoveAttachment:(id)=>setFiles((items)=>items.filter((item)=>item.id!==id)),onSubmit:()=>setSubmits((count)=>count+1),onSuggestionPick:()=>{},onValueChange:setValue,pausing:false,queueCount:0,reasoningOptions:[],reasoningValue:"high",suggestions:[],value});
  const activate=()=>{setPhase("running");setTurns([{id:"live",status:"running",userMessage:{id:"user",role:"user",content:("这是一条用于验证长输入折叠和渐隐效果的中文请求。 ").repeat(24),status:"complete"},workSegments:[{id:"work",activities:[{activityId:"tool",kind:"tool",status:"running",title:"Inspect"}]}]}])};
  const complete=()=>{setPhase("completed");setTurns((items)=>items.map((turn)=>turn.id==="live"?{...turn,status:"completed",workSegments:[{id:"work",activities:[{activityId:"tool",kind:"tool",status:"completed",title:"Inspect"}]}],assistantMessage:{id:"answer",role:"assistant",content:"Done",status:"complete"}}:turn))};
  return <><nav><button id="activate" onClick={activate}>Activate</button><button id="complete" onClick={complete}>Complete</button><button id="disconnected" onClick={()=>setPhase("disconnected")}>Disconnect</button><button id="paused" onClick={()=>setPhase("paused")}>Pause state</button><button id="failed" onClick={()=>setPhase("failed")}>Fail state</button><button id="burst" onClick={()=>setTurns(Array.from({length:30},(_,index)=>({id:String(index),status:"completed",workSegments:[],assistantMessage:{id:"message-"+index,role:"assistant",content:"Long output "+index+" "+"x".repeat(180),status:"complete"}})))}>Burst</button><button id="append" onClick={()=>setTurns((items)=>[...items,{id:"latest",status:"completed",workSegments:[],assistantMessage:{id:"latest-message",role:"assistant",content:"Newest output",status:"complete"}}])}>Append</button><button id="thread-a" onClick={()=>setScrollKey("thread-a")}>Thread A</button><button id="thread-b" onClick={()=>setScrollKey("thread-b")}>Thread B</button></nav><span id="submits">{submits}</span><span id="actions">{actions.join(",")}</span><span id="scroll-key">{scrollKey}</span><AgentChat composer={composer} runStatus={{state,onReconnect:()=>setActions((v)=>[...v,"reconnect"]),onResume:()=>setActions((v)=>[...v,"resume"]),onRetry:()=>setActions((v)=>[...v,"retry"])}} scrollKey={scrollKey} themeTokens={{input:"#123456",surface:"#101820"}} turns={turns} /></>;
}
createRoot(document.getElementById("root")).render(<App/>);
`;
}

async function installAndBuild(root) {
  await run("pnpm", ["install", "--ignore-workspace", "--strict-peer-dependencies", "--no-frozen-lockfile"], root);
  await run("pnpm", ["build"], root);
}

async function writeFiles(root, files) {
  for (const [relative, contents] of Object.entries(files)) {
    const target = join(root, relative); await mkdir(dirname(target), { recursive: true }); await writeFile(target, `${contents.trim()}\n`);
  }
}

async function serveDirectory(root) {
  const server = createServer(async (request, response) => {
    const raw = request.url === "/" ? "/index.html" : request.url;
    const target = join(root, raw.split("?")[0]);
    try { const body = await readFile(target); response.setHeader("content-type", mimeType(target)); response.end(body); }
    catch { response.statusCode = 404; response.end("not found"); }
  });
  await new Promise((resolveListen) => server.listen(0, "127.0.0.1", resolveListen));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("static server did not bind");
  return { url: `http://127.0.0.1:${address.port}`, close: () => new Promise((resolveClose, rejectClose) => server.close((error) => error ? rejectClose(error) : resolveClose())) };
}

function mimeType(path) { return extname(path) === ".js" ? "text/javascript" : extname(path) === ".css" ? "text/css" : "text/html"; }
function collectBrowserErrors(page) { const errors=[]; page.on("pageerror",(error)=>errors.push(error.message)); page.on("console",(message)=>{if(message.type()==="error")errors.push(message.text())}); return errors; }
function freePort() { return new Promise((resolvePort, rejectPort) => { const server=createNetServer(); server.once("error",rejectPort); server.listen(0,"127.0.0.1",()=>{const address=server.address(); if(!address||typeof address==="string")return rejectPort(new Error("port allocation failed")); server.close((error)=>error?rejectPort(error):resolvePort(address.port));});}); }
async function waitForUrl(url, diagnostics) { for(let attempt=0;attempt<100;attempt+=1){try{if((await fetch(url)).ok)return}catch{} await new Promise((resolveWait)=>setTimeout(resolveWait,100));} throw new Error(`server did not become ready: ${url}\n${diagnostics().slice(-2000)}`); }
function run(command,args,cwd){return new Promise((resolveRun,rejectRun)=>{const child=spawn(command,args,{cwd,env:process.env,stdio:"inherit"});child.on("error",rejectRun);child.on("exit",(code,signal)=>code===0?resolveRun():rejectRun(new Error(`${command} ${args.join(" ")} failed (${signal??code})`)));});}
