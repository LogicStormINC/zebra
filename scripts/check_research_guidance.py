"""uv run python scripts/check_research_guidance.py; no model or network calls."""

from datetime import UTC, datetime

from agent_core.harness import HarnessModelStep, HarnessTask
from agent_core.harness.model_step_support import AGENT_EXECUTION_GUIDANCE


def check() -> None:
    # Check the actual shared composition path, including a host-supplied identity.
    for identity in (None, "Host agent identity"):
        task = HarnessTask(
            title="Research", user_input="Verify two official release dates",
            **({"identity_directive": identity} if identity else {}),
        )
        messages = HarnessModelStep().build_initial_messages(task, created_at=datetime.now(UTC))
        assert sum(AGENT_EXECUTION_GUIDANCE in message.content for message in messages) == 1
        system = "\n".join(
            message.content for message in messages if message.role.value == "system"
        )
        for instruction in (
            "source and event terms", "title and snippet", "generic landing page",
            "independent evidence gaps", "paraphrases for the same gap",
            "material conflict", "explicit completeness", "Do not expose private reasoning",
        ):
            assert instruction in system, instruction
        assert "redis.io" not in system and "postgresql.org" not in system
    print("Shared research guidance wired; source and completeness guards retained")


if __name__ == "__main__":
    check()
