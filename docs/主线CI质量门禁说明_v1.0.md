# Zebra Agent 主线 CI 质量门禁说明 v1.0

## 1. 目的

`.github/workflows/quality.yml` 把仓库已经存在并在本地使用的质量命令接入 GitHub Pull Request
和 `main` push。它不是新的构建系统，不改变测试、类型、Lint、Eval 或前端构建语义。

## 2. 触发与权限

- 每个 Pull Request 运行。
- 每次 push 到 `main` 运行。
- `GITHUB_TOKEN` 只有 `contents: read`。
- 同一 ref 的旧运行会在新提交到达后取消，避免浪费并行时间。
- 工作流不读取环境密钥，不调用模型、外部 Provider、SCM 写接口或部署目标。

工作流本身不会配置 Branch Protection。维护者应在首次稳定运行后，把两个 job 设置为合并所需检查：

- `Backend quality`
- `Desktop quality`

## 3. Backend quality

运行环境：

- GitHub-hosted `ubuntu-latest`
- Python `3.12`
- uv `0.11.12`
- `astral-sh/setup-uv` 使用内置缓存，缓存键包含 `uv.lock`

执行顺序：

```bash
uv sync --frozen --all-packages --group dev
make test
make check
```

因此该 job 覆盖：

- 全部 Pytest
- 源码和测试文件大小门禁
- Ruff
- 严格 Mypy
- 发布 Eval

`uv.lock` 在本任务中首次进入版本控制；`--frozen` 确保 CI 不修改锁文件，也不会接受没有进入
锁文件的解析结果。

## 4. Desktop quality

运行环境：

- GitHub-hosted `ubuntu-latest`
- Node `22.17.0`
- pnpm `10.28.2`

执行顺序：

```bash
pnpm install --frozen-lockfile --ignore-scripts
pnpm run "/^check:/"
pnpm build
```

正则脚本选择会运行 `package.json` 中全部当前和未来的 `check:*` 脚本，因此新增确定性桌面检查后
无需重复编辑 workflow。`--ignore-scripts` 保留当前安全安装边界；Tauri 打包不属于该 job。

## 5. Supply-chain 边界

工作流中的 Action 使用完整 commit SHA，并在行尾记录已核对的发布版本：

- `actions/checkout`：`v6.0.2`
- `actions/setup-node`：`v6.4.0`
- `astral-sh/setup-uv`：`v8.1.0`

版本升级必须通过普通 PR，核对官方发布记录并更新 SHA 与注释，不允许把第三方 Action 改为浮动
`main`、`master` 或未审查的分支。

## 6. 本地等价验证

CI 失败时，先使用与 job 相同的命令本地复现。不要在 workflow 中添加跳过参数来绕过失败。

Backend：

```bash
uv sync --all-packages --group dev
make test
make check
```

Desktop：

```bash
cd UI/desktop
pnpm install --frozen-lockfile --ignore-scripts
pnpm run "/^check:/"
pnpm build
```

本地 sync 允许省略 `--frozen` 用于主动更新依赖；提交前必须检查并提交预期的锁文件变化。

## 7. 明确不覆盖

第一版 CI 不执行：

- Tauri 原生打包、签名或发布
- 浏览器视觉回归
- 真实模型或外部网络验收
- GitHub Pull Request 实际创建
- macOS、Windows 或多 Python 版本矩阵
- Branch Protection 设置
- 部署、制品上传、Secret 读取或远程环境变更

这些能力只有在出现独立任务卡、Owned paths、成本预算和失败处理规则后才能加入。

## 8. 验收

- Workflow YAML 可解析。
- Action 均使用核对过的完整 SHA。
- 权限保持 `contents: read`。
- 本地执行 Backend 和 Desktop 等价命令通过。
- PR 上两个 job 均成功后，再申请将它们设为 required checks。
