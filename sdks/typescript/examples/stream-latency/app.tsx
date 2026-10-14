import React, { useCallback, useLayoutEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { ConversationStreamReducer, ZebraClientRuntime } from "@zebra-agent/client-core";
import { AgentMessageList } from "@zebra-agent/react";
import type { AgentMessage } from "@zebra-agent/ui-contracts";
import "@zebra-agent/react/styles.css";

const history: AgentMessage[] = [0, 1, 2].map(index => ({ id: `history-${index}`, role: "assistant", status: "complete", content: `Verified previous answer ${index + 1}` }));
function Replay() {
  const [messages, setMessages] = useState<readonly AgentMessage[]>(history);
  const [timing, setTiming] = useState({ firstObservationMs: 0, firstBodyMs: 0 });
  const [active, setActive] = useState(false);
  const [historicalRenders, setHistoricalRenders] = useState(0);
  const renders = useRef(new Map<string, number>());
  const started = useRef(0);
  const runtime = useRef<ZebraClientRuntime | null>(null);
  const controller = useRef<ReadableStreamDefaultController<Uint8Array> | null>(null);
  const reducer = useRef(new ConversationStreamReducer());
  const write = (name: string, value: unknown) => controller.current?.enqueue(new TextEncoder().encode(`data: ${JSON.stringify({ type: "CUSTOM", name, value })}\n\n`));
  const renderContent = useCallback((message: AgentMessage) => {
    renders.current.set(message.id, (renders.current.get(message.id) ?? 0) + 1);
    return <span>{message.content}</span>;
  }, []);
  useLayoutEffect(() => {
    if (started.current && !timing.firstBodyMs && messages.some(message => message.presentation === "provisional" && message.content)) {
      setTiming(value => ({ ...value, firstBodyMs: performance.now() - started.current }));
    }
    setHistoricalRenders(history.reduce((count, message) => count + (renders.current.get(message.id) ?? 0), 0));
  }, [messages, timing.firstBodyMs]);
  const replay = async () => {
    runtime.current?.stop();
    reducer.current.reset();
    setTiming({ firstObservationMs: 0, firstBodyMs: 0 });
    setActive(true);
    started.current = performance.now();
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
      onObservation: async event => {
        reducer.current.observe(event);
        if (event.name === "zebra.stream.draft") setTiming(value => value.firstObservationMs ? value : { ...value, firstObservationMs: performance.now() - started.current });
        setMessages([...history, ...reducer.current.snapshot()]);
        if (event.name === "zebra.answer_committed") { setActive(false); runtime.current?.stop(); }
      },
    });
    await runtime.current.start();
    while (!controller.current) await new Promise(resolve => setTimeout(resolve, 0));
    write("zebra.stream.recovery_complete", {});
    for (let offset = 0; offset < 40; offset++) {
      write("zebra.stream.draft", { message_id: "message:example", generation_id: "recording", offset, content_delta: offset ? " · text" : "First draft" });
      await new Promise(resolve => setTimeout(resolve, 10));
    }
  };
  return <main style={{ maxWidth: 780, margin: "32px auto", padding: 20 }}>
    <h1>Cloud Agent stream replay</h1>
    <p>Official npm packages · recorded v2 frames · no model or Trench dependency</p>
    <button onClick={() => void replay()} disabled={active}>Replay stream</button>{" "}
    <button disabled={!active} onClick={() => write("zebra.answer_committed", { model_call_id: "example", assistant_message: "Corrected final answer" })}>Commit final</button>
    <p role="status">{active ? "Streaming draft; final has not committed" : "Ready / completed"}</p>
    <output aria-label="Stream timings">First observation: {timing.firstObservationMs.toFixed(2)} ms · First body: {timing.firstBodyMs.toFixed(2)} ms · Historical renders: {historicalRenders}</output>
    <AgentMessageList messages={messages} renderContent={renderContent} />
  </main>;
}
createRoot(document.getElementById("root")!).render(<Replay />);
