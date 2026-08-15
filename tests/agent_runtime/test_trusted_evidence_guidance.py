from pathlib import Path

from agent_runtime.finos_journal_provider import FinosJournalProvider
from agent_runtime.harness import LocalToolGateway


def test_guidance_exposes_only_advertised_trusted_producers(tmp_path: Path) -> None:
    provider = FinosJournalProvider(
        base_url="https://finos.internal",
        task_id="11111111-1111-4111-8111-111111111111",
        grant="opaque-task-grant",
        contract_version="finos.journals.v4",
        model_tool_names=("finos.investor_knowledge.get",),
    )

    guidance = LocalToolGateway(
        tmp_path, finos_journal_provider=provider
    ).trusted_evidence_tools

    assert guidance == {
        "finos.investor_knowledge.get": ("confirmed_investor_knowledge",)
    }
