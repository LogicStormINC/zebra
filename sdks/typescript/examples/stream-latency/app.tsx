import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { ConversationStreamReducer, ZebraClientRuntime } from "@zebra-agent/client-core";
import type { ConversationStreamEvent } from "@zebra-agent/client-core";
import { AgentMessageList } from "@zebra-agent/react";
import type { AgentMessage } from "@zebra-agent/ui-contracts";
import "@zebra-agent/react/styles.css";

const history: AgentMessage[] = [0, 1, 2].map(index => ({ id: `history-${index}`, role: "assistant", status: "complete", content: `Verified previous answer ${index + 1}` }));
const serverGrant = document.getElementById("root")?.dataset.observerGrant === "stdin";
const emptyTiming = { firstObservationMs: 0, firstBodyMs: 0, committedObservationMs: 0, committedBodyMs: 0 };
function Replay() {
  const [messages, setMessages] = useState<readonly AgentMessage[]>(history);
  const [timing, setTiming] = useState(emptyTiming);
  const [active, setActive] = useState(false);
  const [mode, setMode] = useState("replay");
  const [observerOnly, setObserverOnly] = useState(serverGrant);
  const [status, setStatus] = useState("Ready");
  const [historicalRenders, setHistoricalRenders] = useState(0);
  const renders = useRef(new Map<string, number>());
  const started = useRef(0);
  const startedAt = useRef("");
  const replayNumber = useRef(0);
  const runtime = useRef<ZebraClientRuntime | null>(null);
  const controller = useRef<ReadableStreamDefaultController<Uint8Array> | null>(null);
  const reducer = useRef(new ConversationStreamReducer());
  const body = useRef<HTMLDivElement>(null);
  const committed = useRef(false);
  const recovering = useRef(false);
  const observedIds = useRef({ draft: "", committed: "" });
  const write = (name: string, value: unknown) => controller.current?.enqueue(new TextEncoder().encode(`data: ${JSON.stringify({ type: "CUSTOM", name, value })}\n\n`));
  const renderContent = useCallback((message: AgentMessage) => {
    renders.current.set(message.id, (renders.current.get(message.id) ?? 0) + 1);
    return <span data-message-id={message.id} data-presentation={message.presentation}>{message.content}</span>;
  }, []);
  useEffect(() => () => runtime.current?.stop(), []);
  useLayoutEffect(() => {
    if (started.current) {
      const spans = Array.from(body.current?.querySelectorAll<HTMLSpanElement>("[data-message-id]") ?? []);
      const draftVisible = timing.firstObservationMs && spans.find(span => span.dataset.messageId === observedIds.current.draft && span.dataset.presentation === "provisional")?.textContent;
      const canonicalVisible = spans.find(span => span.dataset.messageId === observedIds.current.committed && span.dataset.presentation === "committed");
      if ((!timing.firstBodyMs && draftVisible) || (!timing.committedBodyMs && committed.current && canonicalVisible)) {
        const elapsed = performance.now() - started.current;
        setTiming(value => ({ ...value,
          firstBodyMs: value.firstBodyMs || (draftVisible ? elapsed : 0),
          committedBodyMs: value.committedBodyMs || (committed.current && canonicalVisible ? elapsed : 0),
        }));
      }
    }
    setHistoricalRenders(history.reduce((count, message) => count + (renders.current.get(message.id) ?? 0), 0));
  }, [messages, timing.firstObservationMs, timing.firstBodyMs, timing.committedBodyMs]);
  const stop = () => {
    replayNumber.current++;
    runtime.current?.stop();
    runtime.current = null;
    controller.current = null;
    setActive(false);
  };
  const begin = (nextMode: string) => {
    stop();
    reducer.current.reset();
    committed.current = false;
    observedIds.current = { draft: "", committed: "" };
    recovering.current = nextMode === "live";
    setMessages(nextMode === "replay" ? history : []);
    setTiming(emptyTiming);
    setMode(nextMode);
    setActive(true);
    started.current = performance.now();
    startedAt.current = new Date().toISOString();
    setStatus("Waiting for stream");
    return replayNumber.current;
  };
  const observe = async (event: ConversationStreamEvent) => {
    reducer.current.observe(event);
    const elapsed = performance.now() - started.current;
    if (event.name === "zebra.stream.recovery_start") recovering.current = true;
    if (event.name === "zebra.stream.recovery_complete") { recovering.current = false; setStatus("Recovery complete; waiting for live draft"); }
    if (event.name === "zebra.stream.draft" && !recovering.current) {
      observedIds.current.draft ||= (event.value as { message_id: string }).message_id;
      setTiming(value => value.firstObservationMs ? value : { ...value, firstObservationMs: elapsed });
      setStatus("Streaming draft; final has not committed");
    }
    if (event.name === "zebra.answer_committed" && !recovering.current) {
      committed.current = true;
      const value = event.value as { model_call_id?: string; message_id?: string };
      observedIds.current.committed ||= value.model_call_id ? `message:${value.model_call_id}` : value.message_id ?? "";
      setTiming(value => value.committedObservationMs ? value : { ...value, committedObservationMs: elapsed });
      setStatus("Canonical answer observed");
    }
    setMessages([...(modeRef.current === "replay" ? history : []), ...reducer.current.snapshot()]);
    if (event.name === "zebra.answer_committed" && modeRef.current === "replay") stop();
    if (event.name === "zebra.stream.reset" && (event.value as { reason?: string } | null)?.reason === "authorization_rejected") {
      stop();
      setStatus("Stream authorization rejected; obtain a valid observer credential");
    }
  };
  const modeRef = useRef("replay");
  const replay = async () => {
    modeRef.current = "replay";
    const recording = begin("replay");
    runtime.current = new ZebraClientRuntime({
      baseUrl: "/fixture", clientSessionId: "stream-example", sessionCredential: "synthetic-only",
      streamUrl: "/fixture/stream", streamVersion: 2,
      fetchImpl: async url => {
        if (String(url).split("?")[0] !== "/fixture/stream") return Response.json({ effects: [] });
        return new Response(new ReadableStream({
          start(output) { controller.current = output; },
          cancel() { controller.current = null; },
        }), { headers: { "Content-Type": "text/event-stream" } });
      },
      onObservation: async event => { if (recording === replayNumber.current) await observe(event); },
    });
    await runtime.current.start();
    while (!controller.current && recording === replayNumber.current) await new Promise(resolve => setTimeout(resolve, 0));
    if (recording !== replayNumber.current) return;
    write("zebra.stream.recovery_complete", {});
    for (let offset = 0; offset < 40 && recording === replayNumber.current; offset++) {
      write("zebra.stream.draft", { message_id: "message:example", generation_id: "recording", offset, content_delta: offset ? " · text" : "First draft" });
      await new Promise(resolve => setTimeout(resolve, 10));
    }
  };
  const connect = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    const credentialInput = form.elements.namedItem("sessionCredential") as HTMLInputElement;
    const sessionCredential = String(values.get("sessionCredential") ?? "");
    credentialInput.value = "";
    const grantInput = form.elements.namedItem("hostGrant") as HTMLInputElement;
    const hostGrant = String(values.get("hostGrant") ?? "");
    grantInput.value = "";
    let connection: number | undefined;
    try {
      const base = new URL(String(values.get("baseUrl")));
      const stream = new URL(String(values.get("streamUrl")), base);
      const clientSessionId = String(values.get("clientSessionId") ?? "").trim();
      if (![base, stream].every(url => ["http:", "https:"].includes(url.protocol) && !url.username && !url.password) || base.search || base.hash || stream.hash || base.origin !== stream.origin) throw new Error();
      if (!observerOnly && (!/^[\w-]+$/.test(clientSessionId) || !sessionCredential.startsWith(`${clientSessionId}:`) || sessionCredential.slice(clientSessionId.length + 1).length < 16 || /\s/.test(sessionCredential) || values.get("version2") !== "on" || decodeURIComponent(stream.href).includes(sessionCredential.slice(clientSessionId.length + 1)))) throw new Error();
      if (observerOnly && ((!hostGrant && !serverGrant) || /\s/.test(hostGrant) || values.get("version2") !== "on" || (hostGrant && decodeURIComponent(stream.href).includes(hostGrant)))) throw new Error();
      modeRef.current = "live";
      connection = begin("live");
      runtime.current = new ZebraClientRuntime({
        baseUrl: base.href.replace(/\/$/, ""), clientSessionId: observerOnly ? "observer-only" : clientSessionId, sessionCredential: observerOnly ? "observer-only:unused" : sessionCredential,
        streamUrl: stream.href, streamVersion: 2,
        // No storage: cursor and credential stay in this page's runtime memory.
        fetchImpl: async (input, init) => {
          try {
            if (observerOnly) {
              const target = new URL(String(input), base);
              const allowed = new URL(stream);
              if (target.searchParams.get("recovery") === "full") target.searchParams.delete("recovery");
              if (target.href === allowed.href && (!init?.method || init.method === "GET")) {
                const headers = new Headers(init?.headers);
                headers.delete("X-Zebra-Client-Session");
                if (hostGrant) headers.set("Authorization", `Bearer ${hostGrant}`);
                else headers.delete("Authorization");
                init = { ...init, headers, redirect: "error" };
              } else if (target.href === `${base.href.replace(/\/$/, "")}/v1/client-sessions/observer-only/effects` && !init?.method) return Response.json({ effects: [] });
              else if (target.href === `${base.href.replace(/\/$/, "")}/v1/client-sessions/observer-only/heartbeat` && init?.method === "POST") return new Response(null, { status: 503 });
              else throw new Error("Observer-only transport rejects non-stream requests");
            }
            const response = await fetch(input, init);
            if (connection === replayNumber.current && !response.ok) setStatus(`HTTP ${response.status}; stream unavailable`);
            return response;
          } catch (error) {
            if (connection === replayNumber.current && !init?.signal?.aborted) setStatus("Network/CORS error; check backend origin policy and connectivity");
            throw error;
          }
        },
        onObservation: async event => { if (connection === replayNumber.current) await observe(event); },
      });
      await runtime.current.start();
    } catch {
      if (connection !== undefined && connection !== replayNumber.current) return;
      stop();
      setStatus("Invalid connection: use same-origin HTTP URLs, version 2 and the selected mode credential");
    }
  };
  const format = (value: number) => value ? `${value.toFixed(2)} ms` : "waiting";
  return <main style={{ maxWidth: 780, margin: "32px auto", padding: 20 }}>
    <h1>Cloud Agent stream diagnostics</h1>
    <p>Official npm packages · recorded replay or existing backend v2 observer</p>
    <button onClick={() => void replay()} disabled={active}>Replay stream</button>{" "}
    <button disabled={!active || mode !== "replay"} onClick={() => { write("zebra.answer_committed", { model_call_id: "example", assistant_message: "Corrected final answer" }); }}>Commit final</button>{" "}
    <button disabled={!active} onClick={() => { stop(); setStatus("Stopped"); }}>Stop</button>
    <form onSubmit={event => void connect(event)} autoComplete="off">
      <h2>Real backend observer</h2>
      <p>For the loopback proxy, set Base URL to this page origin and Stream URL to /observer/stream. Observer only verifies real SSE draft/commit rendering; pending effects are synthetic empty and heartbeat is a local 503. Connect to an existing session stream, then trigger its run in your host application. No model request is sent here. Credentials are cleared from the form on connect and kept only in memory.</p>
      <label><input type="checkbox" checked={observerOnly} disabled={active} onChange={event => setObserverOnly(event.target.checked)} /> Observer only (Host Grant; client effects are not verified)</label>
      {[
        ["baseUrl", "Base URL", "url", "http://127.0.0.1:8000"],
        ["clientSessionId", "Client session ID", "text", ""],
        ["sessionCredential", "Session credential", "password", ""],
        ["streamUrl", "Stream URL (absolute or relative to base)", "text", ""],
      ].map(([name, label, type, placeholder]) => <label key={name} style={{ display: "block", margin: "8px 0" }}>{label}{" "}<input name={name} type={type} placeholder={placeholder} defaultValue={serverGrant ? name === "baseUrl" ? window.location.origin : name === "streamUrl" ? "/observer/stream" : "" : ""} required={observerOnly ? name !== "clientSessionId" && name !== "sessionCredential" : true} disabled={active || (observerOnly && (name === "clientSessionId" || name === "sessionCredential"))} autoComplete="off" spellCheck={false} /></label>)}
      <label style={{ display: "block", margin: "8px 0" }}>Host Grant {serverGrant ? "(supplied through runner stdin; not exposed to page)" : "(raw token, no Bearer prefix)"} <input name="hostGrant" type="password" autoComplete="off" required={observerOnly && !serverGrant} disabled={active || !observerOnly || serverGrant} spellCheck={false} /></label>
      <label><input name="version2" type="checkbox" defaultChecked required disabled={active} /> Version 2</label>{" "}
      <button disabled={active}>Connect</button>
    </form>
    <p role="status">{status}</p>
    <p>Mode: {mode} · Start (UTC): {startedAt.current || "waiting"} · performance.now(): {started.current.toFixed(2)} ms</p>
    <output aria-label="Stream timings" data-first-observation-ms={timing.firstObservationMs} data-first-body-ms={timing.firstBodyMs} data-committed-observation-ms={timing.committedObservationMs} data-committed-body-ms={timing.committedBodyMs}>
      First draft observation: {format(timing.firstObservationMs)} · First draft body DOM: {format(timing.firstBodyMs)} · Canonical observation: {format(timing.committedObservationMs)} · Canonical body DOM: {format(timing.committedBodyMs)} · Historical renders: {historicalRenders}
    </output>
    <div ref={body}><AgentMessageList messages={messages} renderContent={renderContent} /></div>
  </main>;
}
createRoot(document.getElementById("root")!).render(<Replay />);
