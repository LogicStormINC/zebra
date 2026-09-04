# Cloud Agent User File Delivery V1

## Decision

Agent-generated deliverables reuse Zebra's existing fenced Artifact metadata
store and versioned object store. V1 does not add a second file database,
public MinIO bucket, browser-visible object key, or persisted presigned URL.
Ordinary tool output, chat execution, and local behavior remain unchanged when
the capability is absent.

## Publication flow

1. The Host Grant must contain `artifact.publish` and a single opaque
   `principal` resource. Without that scope, the Worker does not register
   `files.publish`.
2. `files.publish` accepts exactly one of:
   - generated UTF-8 `content` plus a safe `display_name`; or
   - a workspace-relative regular-file `path`, with symlink and traversal
     rejection.
3. The Host Grant's `max_artifact_bytes` is the publication limit. Zebra
   records SHA-256, media type, size, file name, `kind=user_file`, and the
   exact terminal Tool Event binding before making the Artifact readable.
4. PostgreSQL remains metadata/Event authority. MinIO stores only opaque,
   namespace-derived versioned object keys in the existing private Artifact
   bucket.

## Download flow

1. The Agent emits only `artifact://<uuid>` in the Tool result. Trench maps it
   to its own stable authenticated BFF route and persists structured attachment
   metadata with the assistant message.
   For a successful `files.publish`, AG-UI carries the whitelisted
   `zebra.user_file.v1` JSON envelope in `TOOL_CALL_RESULT.content`; ordinary
   Tool results keep their existing plain-text content.
2. The browser sends its existing Trench product session to Trench only.
3. Trench exchanges a fresh short-lived Host Grant containing `artifact.read`
   and the current user's `trench.history` binding. Browser credentials are not
   forwarded to Zebra.
4. Zebra requires `artifact.read`, resolves the opaque Artifact UUID inside the
   Task, verifies the frozen Task principal, namespace, Event binding, metadata
   lifecycle, object version, size, and digest, then returns raw bytes.
5. Trench returns `private, no-store`, `nosniff`, and attachment disposition.
   Cross-user and missing artifacts are both exposed as 404.

## Isolation and failure behavior

- The broker derives `principal` from the authenticated Trench viewer; callers
  cannot choose it. Grant renewal rejects principal drift.
- A Task permanently freezes its principal. Same namespace/workspace is not
  sufficient to read another user's Task artifacts.
- Publication failure closes only that Tool call. Download failure does not
  affect chat, subscriptions, event/history tools, or existing Artifact reads.
- MinIO is never public and its credentials never reach Trench's browser.
- Existing Artifact retention/reconciliation and version verification apply;
  V1 introduces no second lifecycle.

## Acceptance

- deterministic tests cover inline/path publication, traversal/symlink/size
  rejection, Grant scope separation, stable Trench links, raw private download,
  and cross-principal denial;
- real PostgreSQL + MinIO acceptance writes `kind=user_file`, finalizes it
  against the Tool Event, reads verified bytes, rebuilds projections, and
  downloads the raw payload through the HTTP adapter;
- the full Zebra and Trench gates remain separately reported because unrelated
  baseline failures do not prove or disprove this slice.
