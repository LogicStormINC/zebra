# AG-UI Compatibility Spike

This directory is the complete implementation boundary for
`EMB-AGUI-SPIKE-01`. It validates the pinned official Python SDK before Zebra
defines a production AG-UI adapter.

Planned layout:

```text
tests/spikes/ag_ui/
├── fixtures.py                  # canonical SDK events and resume inputs
├── sse_decoder.py               # independent bounded SSE test decoder
├── test_event_stream.py         # event model and encoder round trips
├── test_interrupt_resume.py     # durable-interrupt protocol assumptions
└── test_forward_compatibility.py# unknown/custom event and schema drift
```

The Spike must not import Zebra applications or production packages. It does
not define the final Domain Event mapping, HTTP route, Worker behavior, Host
authorization, or CopilotKit integration.

This directory intentionally has no `__init__.py`: making it a top-level
`ag_ui` test package would shadow the installed official `ag_ui` SDK.
