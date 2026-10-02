from agent_core.application import (
    MemoryCandidateExtractionCommand,
    MemoryCandidateExtractionService,
)

from tests.agent_core.test_memory_candidates import (
    _completed_session,
    _InMemoryMemoryStore,
    _now,
    _tool_event,
)


def test_env_wrapped_dependency_commands_are_not_memory_candidates() -> None:
    session = _completed_session()
    result = MemoryCandidateExtractionService(_InMemoryMemoryStore()).extract(
        session=session,
        events=[
            _tool_event(
                session=session,
                sequence=4,
                tool_name="command.run",
                metadata={
                    "command": ["env", "UV_CACHE_DIR=/tmp/uvcache", "uv", "venv", ".venv-chart"],
                    "cwd": ".",
                    "exit_code": 0,
                },
            ),
            _tool_event(
                session=session,
                sequence=5,
                tool_name="command.run",
                metadata={
                    "command": [
                        "uv", "pip", "install", "--python", ".venv-chart/bin/python", "pillow"
                    ],
                    "cwd": ".",
                    "exit_code": 0,
                },
            ),
        ],
        next_sequence=6,
        command=MemoryCandidateExtractionCommand(repo_id="zebra-agent", extracted_at=_now()),
    )

    assert result.records == ()
    assert result.events == ()
