# Cloud 官方 Brave Search API 可选接入

日期：2026-10-17。任务：CLOUD-BRAVE-OPTIONAL-01。

## 状态与边界

准备完成，未激活、未配置真实凭据、未查询搜索上游。
Yahoo 保持正常启动默认和回退。可选配置加载后 Brave 仍 disabled，
只允许通过 SearXNG 显式 `!brapi` 查询验收，不自动混合或故障切换。
凭据到位后才开展真实检索验收；未证明召回或延迟收益。

不改 Cloud 工具合同、提示词、模型、高思考、transient_v2、Trench、全局代理。
Cloud 逐次新鲜授权、DNS/SSRF、请求级取消和现有连接复用路径未改。
流协议 transient_v2 与尚未启用的 web_pipeline_v2 是不同概念。

## 实现

- 当前固定 SearXNG 镜像已自带 `braveapi`，使用官方
  `https://api.search.brave.com/res/v1/web/search`，不使用 Brave 网页抓取。
- `docker/web-search/prepare_brave.py`：标准库离线生成配置，无新增依赖。
  读取当前 settings.yml，仅在根 engines 列表插入独立引擎。
  复用原生配置合并：keep_only 先过滤默认引擎，再追加显式定义的 braveapi。
  原生禁用引擎可用 shortcut 显式调用；inactive=false 使其具备注册资格。
- `disabled=true` 保持 Yahoo 单默认；`shortcut=brapi`、timeout=5 秒、
  上游候选 20 条。Cloud 返回最多五条及原有规范化逻辑不变。
- `compose.brave.yml` 仅替换 settings 只读挂载，沿用原镜像、环境和网络。
  create_host_path=false：私有文件不存在时，启动挂载失败，不能自动生成空目录。
- 密钥只进入已忽略的 `docker/web-search/secrets/brave-settings.yml`。
  新目录权限 0700、文件 0600；拒绝覆盖既存文件或符号链接。
  不修改现有 service.env，不把密钥放入 CLI 参数、URL、日志或模型消息。

## 凭据到位后的操作（本轮未执行）

从仓库根目录执行准备命令；交互输入不回显：

```sh
python3 docker/web-search/prepare_brave.py
```

非交互环境可以 `--key-file /absolute/private/key-file` 读取私有文件。
不要把密钥直接写进命令行。脚本不启动、重启或探测服务。
配置缺失、布局漂移、空密钥、控制字符及既存输出均失败退出。

需要更新基线或轮换密钥时，用 `--output` 写入新的私有文件，核对后替换；
不要沿用旧配置快照而遗漏新的基础配置。密钥读取的私有目录须由操作者控制。

凭据准备后，在单独确认检索验收窗口时才加载：

```sh
docker compose -f docker/web-search/compose.yml \
  -f docker/web-search/compose.brave.yml up -d --no-deps searxng
```

这是显式服务替换，不属于准备脚本；本轮未执行。
无前缀查询仍走 Yahoo；`!brapi 查询词` 走 Brave；`!yh 查询词` 显式回退 Yahoo。
还原基础挂载时使用原始启动命令，不带 compose.brave.yml：

```sh
docker compose -f docker/web-search/compose.yml up -d --no-deps searxng
```

本轮没有改变正常启动入口，也没有把上述覆盖配置固化到默认启动。

## 已验证和未验证

`check_brave.py` 是一个使用原生 SearXNG/YAML 的离线 assert 检查。
在当前固定镜像中通过，容器 network=none、根文件系统只读：

```sh
docker run --rm --network none --read-only --tmpfs /tmp \
  -e PYTHONPATH=/usr/local/searxng \
  --entrypoint /usr/local/searxng/.venv/bin/python \
  --mount type=bind,source="$PWD/docker/web-search/check_brave.py",target=/checks/check_brave.py,readonly \
  --mount type=bind,source="$PWD/docker/web-search/prepare_brave.py",target=/checks/prepare_brave.py,readonly \
  --mount type=bind,source="$PWD/docker/web-search/settings.yml",target=/checks/settings.yml,readonly \
  sha256:19f3942fe0f35b873854d86fc1a7fb9e2bcdf18fbdbdfd1035dcba7c9687ee69 \
  /checks/check_brave.py
```

检查覆盖：解析与原生默认配置合并后只启用 Yahoo；Brave 密钥正确转义；
空密钥等输入拒绝；配置布局漂移拒绝；权限、拒绝覆盖/符号链接；
原生 Brave request 的官方 HTTPS 目标、原样查询与请求头密钥。
Compose 合并另行确认只改变 settings 挂载，不改环境、镜像、TLS 或其他卷。
Ruff 与格式检查通过。最初两次离线检查暴露导入路径和 Path.open 参数问题，
已修正；未触及任何运行服务。

未验证：有效密钥认证、实际 !brapi 引擎调度、上游响应、召回、延迟、
该上游在实际负载下的取消及高思考/v2 页面收益。不把离线通过称为生产验收。
原生适配器不显式设置语言，官方默认 search_lang=en；其拼写纠正默认为开启。
需在真实中英文/版本号验收中检查这些边界，不能把默认值当成已证明适合中文。

## 下一步有界验收

凭据到位后固定 24 条不同首次查询及人工确定的可接受来源集合，
Yahoo/Brave 各三次、交错执行，共 144 次；先无模型，不重放历史 Run。
复用 verify.py 的 --query/--expect-source 验证实际来源。
验收专用 !brapi 前缀只负责选择引擎，两臂去掉选择前缀后的查询正文相同。
保留所有失败，比较前五条目标来源覆盖、错误版本、中英文退化、冷热耗时和费用。
初步晋级目标为命中率增加至少 15 个百分点、无明显类别退化，且新增搜索等待
不能抵消节省的补救往返。目标不是当前实测结论。
通过后另做固定四组高思考/transient_v2 页面配对，检查首正文、整轮、
模型/工具次数与 SQL，再决定是否更改默认上游；本次不做默认切换。

官方参数：[Brave Web Search API](https://api-dashboard.search.brave.com/api-reference/web/search/get)。
