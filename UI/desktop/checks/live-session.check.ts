import assert from "node:assert/strict";
import { mergeSessionEvents, pollWhile, readSseEvents } from "../src/lib/live-session.ts";

const event = (id: string, sequence: number) => ({ event_id: id, sequence }) as never;
const first = readSseEvents('data: {"event_id":"a","sequence":1}\n\ndata: {"event_id":"b"');
assert.deepEqual(first.events, [{ event_id: "a", sequence: 1 }]);
assert.equal(first.remainder, 'data: {"event_id":"b"');
assert.deepEqual(mergeSessionEvents([event("a", 1)], [event("b", 2), event("a", 1)]).map((item) => item.event_id), ["a", "b"]);

let refreshes = 0;
await pollWhile(new Promise((resolve) => setTimeout(resolve, 12)), async () => { refreshes += 1; }, 5);
assert.ok(refreshes >= 2);
