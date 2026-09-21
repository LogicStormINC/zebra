from agent_core.application.memory_directives import (
    MemoryDirectiveAction,
    explicit_memory_directive,
)
from agent_core.domain.memories import MemoryType


def test_parses_chinese_and_english_explicit_memory_directives() -> None:
    chinese = explicit_memory_directive("请记住：回复时先给结论。")
    typed = explicit_memory_directive("项目规则：所有迁移都要有回滚验证")
    forgotten = explicit_memory_directive("forget that 回复时先给结论。")

    assert chinese is not None
    assert chinese.action is MemoryDirectiveAction.REMEMBER
    assert chinese.text == "回复时先给结论。"
    assert typed is not None
    assert typed.memory_type is MemoryType.PROJECT_RULE
    assert forgotten is not None
    assert forgotten.action is MemoryDirectiveAction.FORGET


def test_rejects_secret_and_unbounded_forget_directives() -> None:
    assert explicit_memory_directive("记住：password 是 abc") is None
    assert explicit_memory_directive("忘记全部") is None
