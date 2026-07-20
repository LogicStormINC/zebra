# 扩展体系 Phase A 验收记录

> 范围:EXT-0 契约 + EXT-SKILL-01..05 + EXT-MCP-01/02/06(本记录覆盖已落地的 Skill v2 全部 5 卡;Plugin/Hook/Marketplace Locked,待私有云 GA)。
> 源方案:`zebra-agent-ext-plan-docs/docs/Skill_MCP_Plugin扩展体系优化升级方案_v1.0.md`。
> 架构契约:`docs/ADR-014_扩展体系架构.md`。

## 1. 逐卡落地与合并点

| 卡 | 内容 | PR | Merge SHA |
|---|---|---|---|
| EXT-0 | ADR-014 + 状态机契约 + `plugin_manifest.schema.json` + 威胁模型 + EXT 任务板块 | #180 | `c01819a` |
| EXT-SKILL-01 | `SkillMetadata` v2 + `SkillCatalogReason` 枚举(基础域下沉到 `agent_tools/skills_scope.py`) | #180 | `c01819a` |
| EXT-SKILL-02 | `SkillScope`/`ScopedSkillRoot`/content digest + 四根 settings(`SYSTEM/_ADMIN/_REPO`;USER=旧 `ZEBRA_SKILL_ROOTS`) | #180 | `c01819a` |
| EXT-SKILL-03 | `TaskPreparedPayload.skill_components` 任务级快照(catalog→HarnessTask→TASK_PREPARED→workspace_projection→SQLite) | #180 | `c01819a` |
| EXT-SKILL-03 follow-up | skill_components 贯通 handoff events / authority hash / 恢复读取 / API 序列化(模板=mcp_allowlist) | #181 | `68e27a4` |
| EXT-SKILL-04 | 管理面:SQLite 启停状态 + API `/admin/skills` + CLI `skill list\|show\|enable\|disable` + 构造期 catalog 过滤 | #182 | `32b071d` |
| EXT-SKILL-05 | `skills.read` provenance 元数据(digest/scope/version/source)+ 2 个 release-eval case + 重放契约测试 | 本 PR | 待合并 |

> EXT-SKILL-01..03 与 EXT-0 同属 PR #180 的栈式提交(`32bf1b0`/`c402983`/`cdfb548`/`c182b31`),合并点为 `c01819a`。

## 2. 验证基线(EXT-SKILL-05 合入前本地)

- `make check`:file-size(915 文件)、Ruff、strict Mypy(424 源文件)、release eval gate `cases=10 pass_rate=1.00` 全通过。
- `make test`:`1568 passed, 5 skipped`(5 个 skip 为 opt-in 真实 provider/platform smoke)。
- 新增测试:`tests/agent_storage/test_skills_state.py`、`tests/api/test_skills_admin.py`、`tests/cli/test_skills_commands.py`、`tests/test_skills_admin_contract_matrix.py`、`tests/evals/test_skill_eval_replay.py`,以及 `tests/agent_tools/test_skills.py` 的 provenance 断言扩展。

## 3. Skill digest 跨平台稳定性

- `compute_skill_digest`(`packages/agent-tools/src/agent_tools/skills_scope.py`)对规范化字节做 SHA-256:`skill-manifest-v1\n` + frontmatter + `\nskill-body-v1\n` + body。
- 摘要输入只有 frontmatter 文本与 body 字节,**不哈希任何路径分隔符**;`split_frontmatter` 强制以 `---\n`(LF)起头,CRLF 文件会在到达摘要前被拒,故磁盘上恒为 LF,`read_bytes()` 在 Linux/macOS 返回一致字节。
- 结论:digest 在 Linux/macOS 字节稳定。fixture 必须保持 LF-only、以 `---\n` 起、`\n---` 闭;`expected_skill_digest` 由 `compute_skill_digest` 对 fixture 规范字节生成(已固定在 `evals/cases/skill_guided_*.json`)。

## 4. 回滚命令

逐卡按合并点回滚(保留历史,使用 revert):

```
git revert -m 1 32b071d   # 撤销 EXT-SKILL-04(管理面)
git revert -m 1 68e27a4   # 撤销 EXT-SKILL-03 follow-up(贯通层)
git revert -m 1 c01819a   # 撤销 EXT-0 + SKILL-01/02/03(契约与 Skill v2 基线)
```

EXT-SKILL-05 为单提交分支,可 `git revert <本 PR merge sha>` 或直接丢弃对应提交。

数据库迁移均为加性(`skills_state` 表、`workspace_projections.skill_components` 列,均 `CREATE/ALTER ... IF NOT EXISTS`),回滚后旧库不受影响。

## 5. 显式非目标(继承自任务卡)

- 中途启停不影响运行中 Task(Enabled 仅影响新 Task)。
- 不做真实 LLM 技能质量评测(release eval 为契约/计数门)。
- 不做签名或 marketplace provenance。
- Per-task 在网关层按 scoped roots 过滤(scope 真正生效)留作后续(当前 runtime 仍加载扁平 `skill_roots`)。
