from agent_core.domain.events import EventActor, EventType
from agent_core.harness.evidence_ledger import evidence_ledger
from agent_core.harness.models import HarnessEventDraft


def test_ledger_collects_only_successful_explicit_references() -> None:
    events = [
        HarnessEventDraft(
            event_type=EventType.TOOL_EXECUTION_COMPLETED,
            actor=EventActor.TOOL,
            payload={
                "status": "executed",
                "output": (
                    '{"items":[{"original_url":"https://example.test/a"}],'
                    '"ignored":"https://example.test/not-a-reference"}'
                ),
                "metadata": {"artifact_uri": "artifact://report"},
            },
        ),
        HarnessEventDraft(
            event_type=EventType.TOOL_EXECUTION_FAILED,
            actor=EventActor.TOOL,
            payload={
                "status": "failed",
                "output": '{"url":"https://example.test/failed"}',
            },
        ),
    ]

    ledger = evidence_ledger(events)

    assert ledger.successful_tool_results == 1
    assert ledger.failed_tool_results == 1
    assert ledger.evidence_refs == (
        "artifact://report",
        "https://example.test/a",
    )
    assert ledger.artifact_refs == ("artifact://report",)


def test_ledger_without_reference_is_evidence_but_not_citable() -> None:
    ledger = evidence_ledger(
        [
            HarnessEventDraft(
                event_type=EventType.TOOL_EXECUTION_COMPLETED,
                actor=EventActor.TOOL,
                payload={"status": "executed", "output": "Looks good."},
            )
        ]
    )

    assert ledger.successful_tool_results == 1
    assert ledger.has_evidence
    assert ledger.evidence_refs == ()


def test_directory_metadata_path_is_not_a_citable_file_reference() -> None:
    ledger = evidence_ledger(
        [
            HarnessEventDraft(
                event_type=EventType.TOOL_EXECUTION_COMPLETED,
                actor=EventActor.TOOL,
                payload={"status": "executed", "metadata": {"path": "docs"}},
            )
        ]
    )

    assert ledger.evidence_refs == ()


def test_ledger_collects_citable_repo_relative_path_from_tool_metadata() -> None:
    ledger = evidence_ledger(
        [
            HarnessEventDraft(
                event_type=EventType.TOOL_EXECUTION_COMPLETED,
                actor=EventActor.TOOL,
                payload={
                    "status": "executed",
                    "output": "authoritative store details",
                    "metadata": {
                        "path": "packages/agent-storage/src/agent_storage/composition.py",
                        "evidence_refs": [
                            "packages/agent-storage/src/agent_storage/composition.py"
                        ],
                    },
                },
            )
        ]
    )

    path = "packages/agent-storage/src/agent_storage/composition.py"
    assert ledger.evidence_refs == (path,)
    assert ledger.cited_refs(f"Evidence: `{path}`") == (path,)


def test_ledger_collects_explicit_search_evidence_refs() -> None:
    path = "packages/agent-storage/src/agent_storage/postgres/governed_memories.py"
    ledger = evidence_ledger(
        [
            HarnessEventDraft(
                event_type=EventType.TOOL_EXECUTION_COMPLETED,
                actor=EventActor.TOOL,
                payload={
                    "status": "executed",
                    "metadata": {"path": ".", "evidence_refs": [path]},
                },
            )
        ]
    )

    assert ledger.evidence_refs == (path,)


def test_ledger_rejects_absolute_or_parent_traversal_paths() -> None:
    events = [
        HarnessEventDraft(
            event_type=EventType.TOOL_EXECUTION_COMPLETED,
            actor=EventActor.TOOL,
            payload={"metadata": {"evidence_refs": [path]}},
        )
        for path in ("/tmp/private.txt", "../outside.txt", "docs/../outside.txt")
    ]

    assert evidence_ledger(events).evidence_refs == ()
