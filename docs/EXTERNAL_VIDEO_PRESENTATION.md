# External video presentation

`external_video` is a Host-authorized, replayable UI part, distinct from an
Artifact-backed `video` part. The Host resolves an event inside the user's
entitled subscription period and returns a public HTTPS page or media URL.
Neither Zebra nor Trench downloads the video or publishes it to object storage.

The React package builds iframe URLs only for known Bilibili, YouTube and
Vimeo URL shapes. Direct MP4/WebM/Ogv files use the browser's video element.
Other public URLs render as source links; no arbitrary iframe HTML or iframe
URL from a Tool result is accepted. Third-party playback begins only after
the user clicks. Site CSP, embedding restrictions, region/age gates and
expired media links can still prevent inline playback; the original link
remains available.

The paired Trench Host tool is `media.present_external` (`history.read`). Its
result becomes a typed part in the durable Turn stream and snapshot. Existing
`media.import_historical`/`content.present` remain the separate, Artifact-backed
path for media that must be imported into a Session.

Validation boundary: SDK build/type check and 46 tests; paired Trench focused
API, frontend and production build checks. A live authenticated conversation
with a current source video still requires the paired branches to be deployed.
