from agent_core.application import (
    MemoryCandidateExtractionCommand,
    MemoryCandidateExtractionService,
)
from agent_core.domain.memories import MemoryStatus, MemoryType

from tests.agent_core.test_memory_candidates import (
    _completed_session,
    _InMemoryMemoryStore,
    _memory_record,
    _now,
    _tool_event,
)


def test_each_refresh_target_keeps_its_own_bounded_legacy_query() -> None:
    session = _completed_session()
    records = [
        _memory_record(
            session,
            memory_type=memory_type,
            text=(
                "Use the repo default commands: `make sync`, `make test`, `make check`."
                if memory_type is MemoryType.PROJECT_RULE
                else "Run `make test` from `.`."
            ),
            status=MemoryStatus.CONFIRMED,
            source_sequence=(2 if memory_type is MemoryType.PROJECT_RULE else 3),
        )
        for memory_type in (MemoryType.PROJECT_RULE, MemoryType.PROCEDURE)
        for _ in range(120)
    ]
    store = _InMemoryMemoryStore(records=records)

    MemoryCandidateExtractionService(store).extract(
        session=session,
        events=[
            _tool_event(
                session=session,
                sequence=2,
                tool_name="files.read",
                output="""# Zebra Agent Repository Rules
## Local Commands
- `make sync`
- `make test`
- `make check`
""",
                metadata={"path": "AGENTS.md", "byte_count": 100, "truncated": False},
            ),
            _tool_event(
                session=session,
                sequence=3,
                tool_name="command.run",
                metadata={"command": ["make", "test"], "cwd": "."},
            ),
            _tool_event(
                session=session,
                sequence=4,
                tool_name="files.read",
                output="# no extracted governance facts",
                metadata={"path": "AGENTS.md", "byte_count": 31, "truncated": False},
            ),
            _tool_event(
                session=session,
                sequence=5,
                tool_name="tests.run",
                metadata={"command": ["make", "check"], "cwd": ".", "preset": "smoke"},
            ),
        ],
        next_sequence=6,
        command=MemoryCandidateExtractionCommand(
            repo_id="zebra-agent",
            extracted_at=_now(),
            since_sequence=3,
        ),
    )

    assert [query.limit for query in store.queries] == [100, 100]
    assert [set(query.memory_types) for query in store.queries] == [
        {MemoryType.PROJECT_RULE, MemoryType.ARCHITECTURE_FACT},
        {MemoryType.PROCEDURE},
    ]
    assert sum(record.status is MemoryStatus.EXPIRED for record in store.records) == 200
    assert sum(record.status is MemoryStatus.CONFIRMED for record in store.records) == 40
