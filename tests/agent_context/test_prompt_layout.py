from agent_context import (
    CompiledContext,
    ContextItem,
    ContextItemKind,
    ContextProvenance,
    PromptCacheKeyRequest,
    PromptSectionKind,
    build_prompt_cache_key,
    build_prompt_layout,
)


def _context_item(
    kind: ContextItemKind,
    title: str,
    content: str,
    locator: str,
) -> ContextItem:
    return ContextItem(
        kind=kind,
        title=title,
        content=content,
        provenance=ContextProvenance(source_type="file", locator=locator),
        priority=10,
        token_count=5,
    )


def test_build_prompt_layout_splits_items_by_stability() -> None:
    compiled = CompiledContext(
        items=(
            _context_item(
                ContextItemKind.FILE_SNIPPET,
                "AGENTS.md",
                "repo rules",
                "AGENTS.md",
            ),
            _context_item(
                ContextItemKind.REPO_MAP,
                "Repo Map",
                "apps packages tests",
                "/repo",
            ),
            _context_item(
                ContextItemKind.CONVERSATION_SUMMARY,
                "Conversation Summary",
                "current plan",
                "conversation_compaction",
            ),
        ),
        total_tokens=15,
        truncated=False,
    )

    layout = build_prompt_layout(compiled)

    assert layout.stable.kind is PromptSectionKind.STABLE
    assert layout.stable.items[0].title == "AGENTS.md"
    assert layout.semi_stable.items[0].kind is ContextItemKind.REPO_MAP
    assert layout.dynamic.items[0].kind is ContextItemKind.CONVERSATION_SUMMARY


def test_prompt_cache_key_changes_with_tool_manifest() -> None:
    compiled = CompiledContext(
        items=(
            _context_item(
                ContextItemKind.FILE_SNIPPET,
                "README.md",
                "setup instructions",
                "README.md",
            ),
        ),
        total_tokens=5,
        truncated=False,
    )

    first = build_prompt_cache_key(
        PromptCacheKeyRequest(
            compiled_context=compiled,
            task_input="run tests",
            workspace_root="/repo",
            model_profile="gpt-5-codex",
            policy_summary="workspace_write",
            tool_manifest=("files.read", "tests.run"),
        )
    )
    second = build_prompt_cache_key(
        PromptCacheKeyRequest(
            compiled_context=compiled,
            task_input="run tests",
            workspace_root="/repo",
            model_profile="gpt-5-codex",
            policy_summary="workspace_write",
            tool_manifest=("files.read", "tests.run", "git.status"),
        )
    )

    assert first != second


def test_prompt_cache_key_is_stable_for_identical_inputs() -> None:
    compiled = CompiledContext(
        items=(
            _context_item(
                ContextItemKind.TOOL_OUTPUT_SUMMARY,
                "Tool Output Summary",
                "tests passed",
                "tool_output_compaction",
            ),
        ),
        total_tokens=5,
        truncated=False,
    )

    request = PromptCacheKeyRequest(
        compiled_context=compiled,
        task_input="verify tests",
        workspace_root="/repo",
        model_profile="gpt-5-codex",
        policy_summary="workspace_write",
        tool_manifest=("tests.run",),
    )

    assert build_prompt_cache_key(request) == build_prompt_cache_key(request)
