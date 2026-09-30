# Blocked read egress in the Harness

When a declared read-only tool is denied specifically because its external route
is blocked, the policy decision remains `deny` and no gateway call is made. The
Harness records an unsuccessful tool observation containing the policy reason,
then lets the model continue using permitted evidence. The denied call does not
consume an executed-tool slot. Repeating the same call remains subject to the
existing loop guard and model-call budget.

Approval requests and all other policy denials remain terminal or waiting as
before. This does not grant new network access or change policy profiles.

The motivating Trench conversation had already read source and historical
events; its later `web.fetch` to `rsshub.app` was denied under
`mcp-proxy-only`. That denial should not discard the earlier evidence or fail
the whole turn.
