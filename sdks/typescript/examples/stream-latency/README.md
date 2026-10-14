# SDK stream latency diagnostics

From `sdks/typescript`, using Node 22.18–24:

```sh
pnpm build
node examples/stream-latency/run.mjs --check
node examples/stream-latency/run.mjs
```

The check bundles built npm exports, checks HTTP routes, and runs a headless
Chromium replay plus a synthetic-fetch connection through the real form/runtime.
It checks draft/commit DOM timings, authorization headers and empty browser
storage. It uses the already-installed Playwright and needs its Chromium binary.
The runner reuses esbuild already installed with tsx, with no new dependency,
no package-source imports. Open its printed loopback URL.

## Recorded replay

Click **Replay stream**. The exported ZebraClientRuntime parses recorded SSE
frames, ConversationStreamReducer updates messages and AgentMessageList displays
a labeled draft before **Commit final**. Commit final replaces the draft and
removes its label. Historical content render counts remain visible. This mode
requires no credentials, backend, model or Trench.

## Existing BFF with client-session stream authentication

Use **Real backend observer** to supply:

- **Base URL**: your existing Host BFF/API origin, including any route prefix.
- **Client session ID** and **Session credential**: an authorized existing observer
  session, with credential format `<client-session-id>:<session-secret>`.
- **Stream URL**: your existing session's AG-UI v2 stream URL, absolute or relative
  to Base URL. It must share the base URL's origin. Include the backend's required
  v2 selection query, if applicable; the checkbox configures the SDK observer.
- **Version 2**: keep checked; this example requires the v2 draft contract.

Click **Connect**, wait for **Recovery complete**, and trigger the existing
session's run through your normal host application. The example sends no prompt
and calls no model. It uses the real runtime's authorized SSE, pending-effect
reconciliation and heartbeat requests. It mounts no action handlers or controller
fence. Initial recovery messages are rendered but excluded from live timings;
connect before the live run begins to capture its first draft. The live connection
stays open after formal commit until **Stop**, so it can show continued stream
observations. Timings keep the first live draft and first live commit per connection;
stop and reconnect to measure another run.

The backend must permit the printed page origin through CORS, including its
OPTIONS preflight, SDK session authorization headers and `Last-Event-ID`. The
runner uses a random port; the regular BFF mode needs that exact origin approved.
For Public Cloud use the fixed observer proxy below instead.
HTTP rejection or network/CORS errors appear as generic status without response
bodies or credentials. Use the browser Network panel to inspect backend responses
when needed. The optional proxy below has one fixed loopback stream target.

Credentials are read from a password input, cleared on connect, and held only by
runtime memory. They are sent in SDK authorization headers, never added to URLs,
localStorage, sessionStorage, page output or application logs. Do not put credentials
in the Base URL or Stream URL. Stop releases the runtime reference; reload closes
the page's runtime. Browser developer tools can inspect authorized requests.

## Public Cloud API: observer only through fixed loopback SSE proxy

Public Cloud AG-UI requires a signed Host Grant Bearer token; the regular SDK
client-session header alone cannot authorize it. Cloud client effects additionally
require valid Host context and session credential. Cloud's exact approved host
origins usually exclude this runner's random localhost origin.

For a real Cloud API reachable on loopback (or through an existing authorized
loopback forward), start the runner with one fixed task/run URL:

```sh
node examples/stream-latency/run.mjs --stream-upstream 'http://127.0.0.1:8000/agui/threads/<task-uuid>/runs/<run-id>/stream'
```

The flag accepts only `http` on `127.0.0.1` or `::1`, an exact AG-UI task/run path,
and no credentials, query or fragment. It exposes only GET `/observer/stream`;
its only accepted query is `recovery=full`. It streams without caching the body,
forwards only Authorization and Last-Event-ID from the browser request (and sets
Accept to SSE), rejects redirects, and cancels upstream when the browser leaves.
It does not forward or fabricate Origin. Upstream still validates the signed
Host Grant and its task/run authority. No proxy header values are logged.
This temporary diagnostics proxy is not a business BFF.

In the page, check **Observer only**, set **Base URL** to the printed page origin
and **Stream URL** to `/observer/stream`, then put the existing authorized raw
token in **Host Grant** (without `Bearer`). Connect before triggering the run.
Host Grant is cleared from the form immediately, held only in the fetch closure,
and sent only as the exact stream's Bearer header. No client-session header is
sent upstream. With no controller fence/actions mounted, the SDK observes SSE;
its pending-effect query is locally answered with an empty set, heartbeat locally
returns 503, and all other transport requests are rejected. **Client effects and
heartbeat are not validated in observer-only mode.** This validates real SSE
observation and React rendering only; no model request is sent by this page.

To keep the grant out of the browser entirely, an already-authorized operator may
launch `node examples/stream-latency/run.mjs --stream-grant-stdin` and pass exactly
one JSON line with `upstream` and `grant` through the child process's stdin.
Use the existing broker's authorized grant for the exact task/run binding; do not
put the grant in shell arguments, environment dumps, URLs or files. The runner
reads that line once, validates the same fixed loopback upstream, keeps the grant
in process memory and overrides upstream Authorization with it. It exposes only
an enabled-mode flag to HTML. The page defaults to **Observer only**, its own base
origin and `/observer/stream`; **Connect** needs no browser credential. SIGTERM
clears the reference and terminates the process. The proxy never returns the grant.

Run the controlled HTTP proxy smoke without models:

```sh
node examples/stream-latency/proxy-smoke.mjs
```

It verifies exact target/query/origin guards, Bearer/cursor forwarding with no
Origin/client-session forwarding, redirect rejection and upstream cancellation.
The runner `--check` also verifies the Host Grant form with synthetic fetch.
Neither synthetic check substitutes for an authorized actual Cloud draft run.

## Timing boundary

All displayed milliseconds are elapsed from the page's Connect/Replay action,
using `performance.now()`; start UTC and the monotonic origin are also displayed.
**First draft observation** is the first live `zebra.stream.draft` callback.
**First draft body DOM** is the first layout effect that finds nonempty provisional
body text in AgentMessageList after that observation. **Canonical observation**
is the first live `zebra.answer_committed` callback; **Canonical body DOM** finds
its committed message in the DOM. Canonical replacement chunks remain drafts
until that formal event. Output `data-*-ms` attributes expose these numbers for
browser inspection. DOM timestamps measure React commit, not paint or animation.

These browser measurements include connect/recovery wait time and are not model
TTFT or cross-machine latency. Correlate the live observation with the backend's
trace timestamps to isolate server/network/browser work. Recorded replay measures
browser work after synthetic frame production. The static-route check alone does
not prove an authenticated real backend run.
