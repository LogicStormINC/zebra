# 扩展体系 Phase A 验收记录

> 状态:**EXT Phase A 已全部完成并合并到 main(`de4fac7`,2026-07-21)。**
> 范围:EXT-0 契约 + EXT-SKILL-01..05 + EXT-MCP-01/02/06(共 7 PR)。Plugin/Hook/Marketplace Locked,待私有云 GA。
> 源方案:`zebra-agent-ext-plan-docs/docs/Skill_MCP_Plugin扩展体系优化升级方案_v1.0.md`。
> 架构契约:`docs/ADR-014_扩展体系架构.md`;状态机契约 `docs/扩展体系状态机与契约_v1.0.md`;威胁模型 `docs/extension_threat_model.md`。

## 1. 逐卡落地与合并点

| 卡 | 内容 | PR | Merge SHA |
|---|---|---|---|
| EXT-0 | ADR-014 + 状态机契约 + `plugin_manifest.schema.json` + 威胁模型 + EXT 任务板块 | #180 | `c01819a` |
| EXT-SKILL-01 | `SkillMetadata` v2 + `SkillCatalogReason` 枚举(基础域下沉到 `agent_tools/skills_scope.py`) | #180 | `c01819a` |
| EXT-SKILL-02 | `SkillScope`/`ScopedSkillRoot`/content digest + 四根 settings(`SYSTEM/_ADMIN/_REPO`;USER=旧 `ZEBRA_SKILL_ROOTS`) | #180 | `c01819a` |
| EXT-SKILL-03 | `TaskPreparedPayload.skill_components` 任务级快照(catalog→HarnessTask→TASK_PREPARED→workspace_projection→SQLite) | #180 | `c01819a` |
| EXT-SKILL-03 follow-up | skill_components 贯通 handoff events / authority hash / 恢复读取 / API 序列化(模板=mcp_allowlist) | #181 | `68e27a4` |
| EXT-SKILL-04 | 管理面:SQLite 启停状态 + API `/admin/skills` + CLI `skill list\|show\|enable\|disable` + 构造期 catalog 过滤 + `skills_state_path` | #182 | `32b071d` |
| EXT-SKILL-05 | `skills.read` provenance 元数据(digest/scope/version/source 到 TOOL_EXECUTION_COMPLETED)+ 2 个 release-eval case + 重放契约测试 | #183 | `c5f19ad` |
| EXT-MCP-01 | 协议版本协商 `SUPPORTED_PROTOCOL_VERSIONS` + Streamable HTTP transport(`mcp_http.py`,https 强制 + 模块级 SSRF + 禁重定向 + bearer-env)+ `mcp_routing` stdio/http 分流 + `McpHttpServerSettings`(kind:"http") | #184 | `5473467` |
| EXT-MCP-02 | `McpSessionPool`(healthy/degraded/quarantined + 有界退避 acquire/release/health/close,包 `McpProxyTransport`)+ `SessionState` dataclass | #185 | `29c7156` |
| EXT-MCP-06 | elicitation→durable Clarification:`ClarificationContext`/`ClarificationRequestedPayload` 加 `response_schema`/`elicitation_source` + `McpElicitationBridge` + `ZEBRA_MCP_ELICITATION` | #186 | `de4fac7` |

> EXT-0 与 SKILL-01/02/03 同属 PR #180 的栈式提交(`32bf1b0`/`c402983`/`cdfb548`/`c182b31`),合并点 `c01819a`。

## 2. 验证基线(Phase A 合入后 main `de4fac7`)

- `make check`:file-size(916 文件)、Ruff、strict Mypy(**428 源文件**)、release eval gate `cases=10 pass_rate=1.00` 全通过。
- `make test`:**`1605 passed, 5 skipped`**(5 个 skip 为 opt-in 真实 provider/platform smoke)。
- 本史诗累计新增约 80 个测试,覆盖:catalog 启停过滤、任务快照贯通、handoff authority hash、恢复读取、API/CLI admin、provenance 元数据、release-eval 重放、协议协商(接受/拒绝)、HTTP transport(discovery/execute/SSRF/https/bearer-env)、settings http 解析、session pool 健康退避、elicitation schema/桥/契约矩阵。

## 3. Skill digest 跨平台稳定性

- `compute_skill_digest`(`packages/agent-tools/src/agent_tools/skills_scope.py`)对规范化字节做 SHA-256:`skill-manifest-v1\n` + frontmatter + `\nskill-body-v1\n` + body。
- 摘要输入只有 frontmatter 文本与 body 字节,**不哈希任何路径分隔符**;`split_frontmatter` 强制以 `---\n`(LF)起头,CRLF 文件会在到达摘要前被拒,故磁盘上恒为 LF,`read_bytes()` 在 Linux/macOS 返回一致字节。
- 结论:digest 在 Linux/macOS 字节稳定。fixture 必须保持 LF-only、以 `---\n` 起、`\n---` 闭;`expected_skill_digest` 由 `compute_skill_digest` 对 fixture 规范字节生成(已固定在 `evals/cases/skill_guided_*.json`)。

## 4. MCP 安全要点(Phase A 落地的硬地板)

- **传输**:stdio 保留;新增 Streamable HTTP,**https 强制**(http 直接拒)、**每次 request 预检** `reject_non_public_resolution`(已提为 `web_gateway.py` 模块级,port 参数,旧私有名留 alias)、**禁重定向**(`_NoRedirectHandler`)。
- **凭证**:bearer token 只存 env 变量名(`bearer_token_env`),transport 在 `execute()` 内 `os.environ[...]` 解析,**不缓存、不入 manifest/event/log**;模型 API key 不会泄漏到 MCP server。
- **协议**:`SUPPORTED_PROTOCOL_VERSIONS = {2025-06-18, 2025-11-25}`;client 发 latest,校验 server 返回版本,fail-closed。
- **不可信输出**:MCP 工具结果恒带 `UNTRUSTED MCP OUTPUT (...)` 标签 + `untrusted_output` 元数据;elicitation 不绕过 Policy/Approval。
- **allowlist**:仍是精确 `mcp.<server>.<tool>` allowlist,不以向量搜索替代;`mcp_routing._partition_allowlist` 按种分区,孤儿工具仍报 unavailable。

## 5. 回滚命令

逐卡按合并点回滚(保留历史,使用 revert):

```
git revert -m 1 de4fac7   # 撤销 EXT-MCP-06(elicitation 桥)
git revert -m 1 29c7156   # 撤销 EXT-MCP-02(session pool)
git revert -m 1 5473467   # 撤销 EXT-MCP-01(协议协商 + HTTP transport)
git revert -m 1 c5f19ad   # 撤销 EXT-SKILL-05(provenance + eval)
git revert -m 1 32b071d   # 撤销 EXT-SKILL-04(管理面)
git revert -m 1 68e27a4   # 撤销 EXT-SKILL-03 follow-up(贯通层)
git revert -m 1 c01819a   # 撤销 EXT-0 + SKILL-01/02/03(契约与 Skill v2 基线)
```

数据库迁移均为加性(`skills_state` 表、`workspace_projections.skill_components` 列,均 `CREATE/ALTER ... IF NOT EXISTS`),回滚后旧库不受影响。

## 6. Phase A 显式非目标 / 待 Phase B

- **真正的 server-initiated `elicitation/create`**:Phase A 是合成器(MCP-06);async stdio reader + HTTP SSE push 通道留 Phase B。
- **完整 SSE 流式**(MCP-01):Phase A 仅 JSON-over-POST + 单消息 `text/event-stream` 解析。
- **OAuth/PKCE/token 刷新/DCR**(MCP-03)、**Audience/Scope/Egress 全量策略**(MCP-04)、**structured content & Artifact 投影**(MCP-05):未在 Phase A 范围。
- **长寿命 stdio 进程 watchdog**(MCP-02 非目标):当前 spawn-per-call,无需看护。
- **runtime 贯通 scoped roots**:网关仍加载扁平 `skill_roots`(USER);system/admin/repo 三根未进 runtime,SKILL-04 的 per-scope 过滤运行时仅对 USER 生效(非 bug,覆盖待补)。
- **Plugin/Hook/Marketplace**:全 Locked,待私有云 GA + 签名/SBOM/扫描/撤销/kill switch。
- **新扩展事件(§13 extension_*  等)与版本级 Eval/可观测指标**:待对应 epic 落地。
