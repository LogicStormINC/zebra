# CLOUD-DEPLOY-HELM-01 Kubernetes/Helm 应用部署

| 项目 | 结论 |
| --- | --- |
| 交付 | fail-closed Helm chart：migration Job、API、Worker、Service、PDB |
| Profile | 只接受 `cloud`/`production`，固定 `gvisor` + workspace quota |
| 镜像 | repository + `sha256` digest，禁止 floating tag |
| 凭据 | 只引用预先创建的 Kubernetes Secret，不在 chart 生成密码 |
| 当前证据 | 静态 chart/schema、`helm lint/template`，以及隔离 Linux `colima-zebra-gvisor` 的真实 Helm 安装均通过 |
| 生产含义 | 证明本地 Linux/gVisor 部署契约，不构成 managed cluster、HA 或生产 rollout 批准 |

Chart 位于 [`deploy/helm/zebra-agent/`](../deploy/helm/zebra-agent/)。它延续已验证的
Docker application overlay，但把进程边界搬到 Kubernetes：migration 作为 pre-install/
pre-upgrade Job，API 和 Worker 使用独立 Deployment，API 通过 ClusterIP Service 暴露。

## 1. Fail-closed 输入

`values.schema.json` 要求：

- `image.repository` 与符合 `sha256:<64 hex>` 的 digest；
- `profile` 为 `cloud` 或 `production`，`runtimeClassName=gvisor`，
  `runtimeImage` 非空，`workspaceQuota.enabled=true`；
- deployment/authority/history/continuation namespace；
- PostgreSQL DSN、S3 access/secret、Redis URL、Memory signing key 的 Secret name/key；
- API/Worker 至少 2 replicas 及 resources。

模板同时使用 Helm `required`，因此即使调用方跳过 schema 校验，缺少这些值也会在
render 时失败。Chart 不创建 `Secret`，数据库密码、S3 secret、Redis URL 和 signing
key 只能来自 operator 预先创建的 Secret refs。

## 2. 资源与安全边界

- migration Job 使用 `python docker/migrate.py`，`backoffLimit=0`，成功后按 hook policy
  清理；API/Worker 不执行隐式 migration；
- API readiness/liveness/startup probes 访问 `/health`；Worker 使用独立 Deployment；
- API/Worker 各有 `minAvailable: 1` 的 PDB，默认 2 replicas 和显式 requests/limits；
- 所有 Pod 使用 RuntimeClass `gvisor`、non-root UID/GID `65532`、RuntimeDefault seccomp、
  `readOnlyRootFilesystem`、`allowPrivilegeEscalation=false`、drop ALL capabilities，
  并关闭 ServiceAccount token automount；
- image 使用 digest，模板不包含数据库 password literal，也不把 secret 内容写进 ConfigMap。

## 3. 使用与验证

先创建外部 Secret（示意，不把值提交到仓库），再执行：

```bash
helm lint deploy/helm/zebra-agent \
  --set image.repository=ghcr.io/acme/zebra-agent \
  --set image.digest=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --set deploymentNamespace=prod-zebra \
  --set runtimeImage=ghcr.io/acme/zebra-runtime@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb \
  --set secrets.databaseUrl.name=zebra-database \
  --set secrets.s3.name=zebra-s3 \
  --set secrets.liveRedisUrl.name=zebra-live \
  --set secrets.memorySigningKey.name=zebra-memory \
  --set config.authorityIssuer=prod-zebra \
  --set config.historyScopeNamespace=prod-zebra-history \
  --set config.continuationScopeNamespace=prod-zebra-continuation \
  --set config.s3Endpoint=https://s3.example.invalid

helm template zebra deploy/helm/zebra-agent --values deploy/helm/zebra-agent/values.yaml
```

本 worktree 的静态测试验证 YAML/template 必需片段、schema digest/secret/runtime 约束和
无密码 literal；`helm 4.2.3 lint` 与 `helm template` 已通过，模板渲染出 7 个资源，默认
值按 schema fail closed。

## 4. 隔离 Linux Helm 验证

在 `colima-zebra-gvisor`（Ubuntu 24.04.4、k3s `v1.34.8+k3s1`、containerd `2.3.1`）中，
使用当前分支构建的 ARM64 镜像和临时 PostgreSQL/Redis/MinIO 依赖完成一次真实安装：

- migration pre-install hook、API Deployment `2/2`、Worker Deployment `2/2` 和 Service
  均成功；首次安装暴露 ServiceAccount hook 顺序缺陷，已将 ServiceAccount 设为
  `pre-install,pre-upgrade`、weight `-20`，migration 为 `-10`，并补充回归测试；
- 四个 cloud-agent Pod 的 `runtimeClassName=gvisor`，容器 `/proc/version` 为
  `4.19.0-gvisor`，运行 UID `65532`；
- API Pod 内部 `/health` 返回 `status=ok`、`profile=production`、`runtime_class=gvisor`、
  `fallback_allowed=false`；Worker 删除一个 Pod 后 Deployment 自动恢复为 `2/2`；
- PostgreSQL migration 达到 v17，Host registry seed 成功；验证结束后 Helm release 和
  namespace 均删除，未留下集群资源。

这是隔离 Linux task-level evidence，不是托管 Kubernetes、生产 HA 或 rollout 批准。

## 5. 明确后续门

本卡不实现 cluster-level NetworkPolicy、gVisor RuntimeClass、managed PostgreSQL/S3、
PITR、滚动发布或 Trench。`CLOUD-K8S-GVISOR-E2E-01` 仍需真实测试集群验证长任务跨
Worker restart、quota、隔离和资源清理；Helm render 通过也不能单独宣称生产部署完成。
