# Agent Definition 威胁模型 v1.0

- 方案编号：`AGENT-DEF-TRUST-01`
- 状态：`Done`（实现链 REG→DRAFT→BIND→MEM→TRUST→EVAL→PUB 的信任收口）
- 基线：`zebra-cloud-trench`
- 范围：Definition Registry、Draft/Version 物化、Task 绑定、Definition 域
  governed Memory、发布 Eval 门与受控发布 API 的内容信任与权限边界

## 1. 威胁模型摘要

| 资产 | 信任边界 | 主要威胁 |
| --- | --- | --- |
| Definition 元数据（Registry v19） | 发布者授权 grant ceiling | 跨 issuer/namespace 越权、引用替换 |
| 不可变 Version/digest | canonical digest 自校验 | 内容篡改、未固定引用 |
| Task 绑定 Snapshot | TASK_PREPARED 事件 + 恢复 digest 校验 | 回读 mutable draft、引用替换 |
| governed Memory 新写 | `(authority_issuer, namespace_id, definition_id)` | legacy key 伪隔离、部分 scope 写入 |
| Release 发布 | 发布 Eval 门 + 发布者授权 | 无门发布、跳过 digest 校验 |
| deprecate/revoke | typed actor/reason/enforcement | 普通 actor 冒充 security revocation |

## 2. 信任规则（实现位置：`agent_security/agent_definitions.py`）

1. **内容信任永不授权**：Snapshot 只声明解析后的 identity/digest，不 grant
   Tool、网络、Memory 写入或发布能力。`assert_snapshot_grants_nothing` 拒绝
   含 grant/approve/bypass/allow-all/unrestricted 标记的引用。
2. **三类 authority 独立追踪**：publisher grant（
   `PublisherGrantPort.ceiling_for`）、Definition Snapshot（TASK_PREPARED 嵌套
   字段）、Attempt authority（`ExecutionAuthoritySnapshot`）互不推导；Snapshot
   不含 grant/subject/token。
3. **跨 issuer/namespace fail closed**：`assert_scope_authority` 与
   `AgentDefinitionPublicationService._require_grant` 同时校验 namespace 与
   issuer；缺失 grant 一律拒绝。
4. **引用替换 fail closed**：`assert_no_reference_substitution` 要求 Snapshot
   的 definition_digest 与绑定 Version 完全一致；发布门
   `PublicationGateEvidence` 校验 version_id + digest 与目标 Version 精确匹配。
5. **Prompt injection fail closed**：`assert_no_injected_content` 对
   metadata/引用做归一化扫描（连字符/下划线视为空格），拒绝
   ignore-previous-instructions/system-prompt/override-policy 等标记。
6. **撤销无旁路**：Release continuation policy 不能绕过外部 authority、
   Credential、Approval 或 Security 撤销；immediate enforcement 需要
   security-revocation actor 白名单（`security_revocation_actors`），普通
   actor 只能选择 safe-boundary。

## 3. 已验证的攻击路径（`tests/test_agent_definition_trust_contract_matrix.py`）

- 内容引用声明 allow-all/bypass → 拒绝（内容信任不授权）。
- 无 grant / namespace 错配 / issuer 错配 → fail closed。
- Snapshot digest 与 Version digest 不一致 → fail closed。
- 引用中含注入标记（含连字符变体）→ fail closed。
- 发布门证据指向不同 Version 或 digest → 拒绝发布。

## 4. 非目标

本模型不覆盖：外部 OIDC/JWKS 验签（TRUST 卡只固定内部边界）、Redis/AG-UI
链路、Trench 业务授权、生产多租户网络隔离。external verifier 接入后仍需
保持本模型的 fail-closed 语义。
