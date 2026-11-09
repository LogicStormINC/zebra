# runtime-gate-termination/1

[Implementation/proof boundary](../../CA-P5-02A_gate_termination.md). Separate machine read/terminate
authority and exact original raw gate request. Noncommit proof requires atomic durable fence; missing
original/termination GET is never proof. Already committed preserves its receipt, no reverse effects.
`contract.json` canonical SHA256 is `digest.txt`; OpenAPI derives from Native strict domain models.
No Task/process/fleet/executor termination or activation authority. Existing gate v1 contract unchanged.
