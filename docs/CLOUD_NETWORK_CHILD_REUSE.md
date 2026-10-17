# Cloud network critical path review

The fixed real search cohort shows the first committed body is dominated by the critical path through model planning, two parallel searches, two parallel official fetches, and the candidate model's first token. Native network profiles show roughly 0.32–0.41 seconds of Python child import per request, but the larger variable components are public DoH (about 0.4–2.0 seconds) and TLS/response waiting (about 0.1–2.0 seconds). Search and fetch pairs already start concurrently.

The native child is deliberate: cancellation can terminate a blocked resolver, TLS handshake, or response read and then reap the process before publishing output. Moving the request into the worker, caching public DNS across requests, or sharing a child across concurrent requests would weaken that boundary or serialize the two parallel requests. Therefore this slice makes no speculative production change. The runnable guard below protects the measured safety invariants while a future egress driver can provide connection pooling and bounded cancellation in one place.

## Check

```sh
python scripts/check_native_network_reuse.py
```
