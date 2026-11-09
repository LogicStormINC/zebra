# Native runtime-gates/1

[OpenAPI](openapi.json) · [canonical semantics](contract.json) · [digest](digest.txt) ·
[domain/proof/operation guide](../../CA-P5-01_runtime_gates.md).

Implemented Native GET/POST, immutable original journal and explicit namespace drain/open.
No executor, automatic POST retry, Controller claim, process-stop or global activation authority.
The digest header must match the embedded Native constant; scope/current approval and read right
are independent from business Agent auth. Only owned disposable validation is performed.

Schema artifacts are exported from GateCommand/GateReceipt/BundleScope; response schemas constrain
proof escalation. Final source commit and tests are in the task's evidence, not a claim of deployment.
