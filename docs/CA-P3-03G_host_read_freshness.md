# CA-P3-03G Host 写后读取新鲜度

配对 Overdoze OD-P3-CLOSEOUT 的实际业务验收，发现 `case.get(item_id)` 在
`case.open` 成功后被误判为重复调用，因而无法完成写后验证。
业务 Host Tool 已返回真实业务版本；不能关闭完成门禁来绕过该问题。

## 根因和修复

`record_tool_freshness` 使用带 authority/namespace/Host 的 `resource:<sha256>`
记录 Host 资源证据；循环守卫却根据裸参数构造 `item_id:item-42`，二者不能匹配。
三个串行/并发调用位置复用 `can_refresh_repeated_read`，因此只修复该共享函数。

当元数据存在 qualified resource epoch 时，允许已经声明只读的工具在 mutation epoch
推进后重新观察。成功读取后记录其 fingerprint epoch，不能在同一 epoch 无限制重复。
这是一项保守的重新观察许可，不从参数推断业务权限，也不生成验证证明。
无 qualified 资源的旧参数匹配路径和旧历史字节保持原样。

实际执行仍经过当前授权/资源绑定；完成仍由既有 `record_tool_freshness` 检查
精确 qualified resource、read/commit version、后置条件和 observed epoch。
其他资源、旧版本、失败后置条件或并发旧 epoch 均不能完成验证。
重新读取不授予写入重试；unknown POST、Controller/Run 和 Coverage 机制不变。

## 检查与交付

最小回归 `tests/agent_core/test_host_read_freshness.py` 验证匹配资源可重新读取、
同 epoch 不重复、下一 mutation 可重新观察，及四组错误证明不能通过完成门禁。
同时运行既有 quality gates、完整 make test/check；SDK 保持现有公开合同。
实际 Host Tool/业务 PG/UI/Worker 固定发布源验收由消费者单独留证。

证据放在 `docs/evidence/ca-p3-03g/`。本片不部署、不生产迁移、不整合 main、不发布 npm，
不修改已封存收据、历史数据、旧合同 pin 或 Coverage 证明。

最终门禁：make test 11143通过/3067条件跳过；make check含30eval通过；定向31、SDK173/check通过。状态Review，合并和消费者固定源验收分别记录。
