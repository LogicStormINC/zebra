# Cloud Runtime 首正文延迟运维

本轮复用已有常驻 Worker、共享模型 HTTP 客户端和节点 readiness。不引入后台模型请求、运行容器池或跨租户沙箱复用。消费端通过公开 v2 协议接入；本文不依赖 Trench 业务逻辑。

## 启用和回滚

Cloud composition 显式设置 `ZEBRA_RUNTIME_DEFER_PROVISION=true`。配置默认 false，SQLite/CLI 原行为保持。普通已物化 Host 上下文且无需恢复旧 runtime/spec/快照的 attempt 才按需分配；工程 workspace、未知依赖及恢复不确定的路径仍 eager。所有 policy 允许的本地工具保守触发准备，Host/Client/management 按原网关路由。保留工作区物化、目录校验和本地 Web cache 初始化；“零 OCI 实例”不代表“零文件系统访问”。

关闭配置使新 attempt 回到 eager；在途 attempt 沿原 owner/fence 清理，不重新执行模型。仅在受影响 Worker 空闲时替换镜像；保留 API/Worker 镜像 digest 及配置来源。完整 STOP 及流存储 SQL80% 验收独立进行。

## 节点准备

1. 配置明确 Docker endpoint、mTLS、固定 image digest 和 runtime handler；不要通过可变默认 Docker context 选择目标。
2. 在节点准入时将配置的 `ZEBRA_RUNTIME_IMAGE` 提前 pull 到同一个目标 daemon，并 inspect 验证 RepoDigests 含该完整引用。镜像缺失时拉取属于节点准备，不应在用户首轮请求中拉取。
3. 使用既有 `python -m zebra_agent_worker.runtime_preflight` 检查 engine/runsc capability，再使用既有 recreate 脚本或受控 composition 更新服务。
4. 记录 daemon identity、Docker server version、runsc 二进制版本、CPU/内存和镜像 digest。`/info` 的 handler 注册不等于已读取 runsc 二进制版本；无法读取的项目明确标为未核对。
5. 验收 sandbox-required 路径的真实命令、PG runtime instance/fence 和清理；只有 `/health` 不代表执行验收。

每次新沙箱准备继续读取新鲜 daemon identity。共享连接复用传输，不能缓存身份结果或跳过 authority/fence。Worker 已在 `main.py` 生命周期内共享 `httpx.Client`，无需再叠加连接池。

本地本轮只读节点检查：固定 Python digest 已缓存，runsc handler 已注册，Docker29.1.3，10CPU，约16.8GB内存；未创建容器、未调用模型。runsc 二进制版本未通过 `/info` 暴露，不能据此宣称版本验收。真实 PG/gVisor 命令与清理另有验收证据。

## 定位剩余等待

分别记录提交→Run建立、Run→commandAccepted、accepted→实际模型 HTTP、Provider→首正文、首正文→Redis/API/SDK/DOM、正式结果同步。模型事件时间和 HTTP 发出时间单独命名；跨进程时间使用 UTC，浏览器端到端用单调时钟。

既有 OpenAI-compatible/DeepSeek 流式路径区分 reasoning 与公开正文。保持用户选择的模型和 effort；Provider 排队、推理和路由变化不能通过本地连接池保证消除。需要实验时另行固定 workload 和质量条件，不静默换模型。

冷进程、冷地址解析、冷 TLS、镜像缺失和新 Run 创建新容器是不同条件。本轮镜像就绪、共享连接及按需分配降低平台等待；没有清空正常节点缓存来制造“冷启动”对照，不将小样本尾延迟当生产 SLA。

后续运行池/进程快照仅在 sandbox-required 的创建成本仍主导时另立 ADR，明确不可变容器绑定、领取/fence、工作区隔离和 GC。接触业务数据的实例不回池。
