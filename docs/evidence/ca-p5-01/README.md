# CA-P5-01 evidence

Status: verified / Review. Final make test11197 passed/3067 conditional skips in1228.21s;
make check1436 typed sources/30Eval passed. [Gate/log summary](validation.json), [frozen source files](source-manifest.json). [Contract and proof boundaries](../../CA-P5-01_runtime_gates.md).

21 final focused checks passed; earlier68 adjacent checks passed before final retention hardening.
Actual owned PostgreSQL, original GET through independent API process, Worker execution predicate,
read-only engine failure, lease expiry/current scope/permission/CAS and reserved-open boundary covered.
The first full test candidate was deliberately interrupted after7810 passed/2181 skipped to include
retention recovery and inherited-observer fixes; it is NOT counted as a passing full gate.

[Actual HTTP outputs](http-responses.json) contain fixture IDs/digests only, no credential.
[Full cloud composition check](composition_acceptance.py) creates only owned disposable PG via
existing fixture, passes explicit synthetic HTTPS business Origin to the real app factory, then
calls the actual scoped machine route. No HostGrant/Controller/Task/model/object request is sent.
Run from repo root: `uv run python docs/evidence/ca-p5-01/composition_acceptance.py`.

Native Registry Release/Version fixtures are explicit setup, not a real Eval/model/deployment.
Positive Worker qualification here is trusted-local development mode; failure of hard engine
preflight is tested, production gVisor/rootless/image/network/provider/fleet shutdown is unverified.
ASGI/real DB/process proof is distinct from HTTPS/Ingress/production HA or a deployed Compose S1.
Original histories/receipts/Coverage and frontend mock/BFF remain untouched. No production migration.
