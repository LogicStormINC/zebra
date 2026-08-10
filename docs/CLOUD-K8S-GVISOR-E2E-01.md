# CLOUD-K8S-GVISOR-E2E-01 Kubernetes gVisor 端到端演练

本任务提供一个 fail-closed 的真实集群 runner，而不是把 Helm render 或普通
runc 集群冒充 gVisor 证据。runner 要求当前 context 存在 Ready node 和
`RuntimeClass/gvisor`，且其 handler 必须是 `runsc`；缺失任一项都会失败并写入
结构化结果，不会回退到 `crun`/`runc`。

## 演练内容

- namespace ResourceQuota 限制 Pod、CPU、内存、PVC 和 storage；创建 128Mi PVC
  必须被 64Mi `requests.storage` 拒绝；
- API-shaped Deployment 与 Worker Job 使用同一 digest-pinned Python image、
  gVisor、non-root/read-only rootfs、RuntimeDefault seccomp、drop ALL 和显式资源；
- default-deny NetworkPolicy 只允许 DNS 与 `app=worker` 到 API 的 8080 ingress；
  blocked probe 必须得到连接拒绝/超时；
- Worker 把 checkpoint 写入 PVC。删除正在运行的 Pod 后，Job 新 Pod 必须从旧
  checkpoint 继续并完成长任务；
- `EXIT` trap 收集 runtime class、Pod/log、quota/policy 和 restart 证据，然后删除
  专用 namespace；清理失败会使 runner 失败。

## 运行

需要一个 Linux Kubernetes 集群、`RuntimeClass/gvisor`（handler=`runsc`）、已启用
NetworkPolicy 的 CNI、默认 StorageClass 和可拉取的 digest 镜像。凭据通过现有
`KUBECONFIG`/context 提供，不写入仓库。

```bash
ZEBRA_K8S_CONTEXT=gvisor-ci \
ZEBRA_K8S_TEST_IMAGE=python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b \
ZEBRA_K8S_EVIDENCE_DIR=/tmp/zebra-k8s-evidence \
bash tests/k8s/gvisor/run-e2e.sh
```

GitHub 手动 workflow 位于 `.github/workflows/k8s-gvisor-e2e.yml`，使用带
`linux/kubernetes/gvisor` labels 的 self-hosted runner；这样不会在没有真实集群
时产生绿色的“跳过”结果。

## 当前证据边界

本机 OrbStack Kubernetes 可启动并通过 API readiness，但当前只有 `crun`、`lunatic`、
`spin` 等 RuntimeClass，没有 `gvisor/runsc`；因此本任务尚未有真实 gVisor E2E
通过记录。直接运行 runner 会在 RuntimeClass preflight fail closed，这是预期安全
行为；未将普通集群、Helm template 或 Docker gVisor smoke 计为本卡完成。
