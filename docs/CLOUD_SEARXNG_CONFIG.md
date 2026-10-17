# Cloud Agent SearXNG configuration

2026-10-18（Asia/Shanghai）。适用于当前受控出口、免密钥、私有机器调用环境。
这是当前可验证的推荐配置，不是任何网络环境下的全局最优引擎组合。

## 选择依据

- 官方 [Search API](https://docs.searxng.org/dev/search_api.html) 支持 JSON，
  未开启的 format 返回403；公共实例常禁用机器接口。保留私有实例和明确 JSON。
- 官方 [Limiter](https://docs.searxng.org/admin/searx.limiter) 面向阻挡可疑机器人，
  依赖 Valkey 和正确客户端 IP。此实例为内部 Agent 服务，保持 limiter=false，
  不额外加浏览器挑战或共享 Worker IP 限制；入口仍是既有受控 HTTPS/授权工具链。
- 官方 [outgoing](https://docs.searxng.org/admin/settings/settings_outgoing.html)
  明确更长超时会延长整次搜索。保留5s引擎预算、6s上限和已有连接池/HTTP2，
  不通过延长超时或自动广播多个失败引擎掩盖上游问题。
- 官方 [settings](https://docs.searxng.org/admin/settings/settings.html) 明确
  SEARXNG_SETTINGS_PATH 优先于 /etc/searxng/settings.yml；原部署指向镜像内
  zebra-exa-settings.yml，挂载文件的后续修改不会被该进程读取。
- [维护者讨论5651](https://github.com/searxng/searxng/discussions/5651)
  记录主流上游的反爬问题。该讨论里“Bing免费API”的建议后来被作者撤回，
  不能作为可实施方案。Google/DDG 本出口既有403/CAPTCHA/召回失败记录见
  CLOUD_KEYLESS_RECALL.md；本轮未重复这些组合，也未增加挑战求解或出口轮换。
- 官方 [Yahoo](https://docs.searxng.org/dev/engines/online/yahoo.html) 使用缓存24h
  的 YBV cookie。保留持久 cache 卷；Yahoo/Exa/网络/取消代码均与旧正常镜像逐字相同。

## 当前配置

| 项目 | 值与理由 |
| --- | --- |
| 默认引擎 | Yahoo 唯一默认；避免未经资格验证的跨引擎 fan-out |
| 可选引擎 | Exa `!exa`，disabled=true/inactive=false，fast；不自动调用 |
| 其他显式选择 | 保留既有 Bing/Sogou/360/微信公众号，disabled=true；未新增可用性声明 |
| 搜索语言 | all；模型查询可能中英混合，不再强制 lang_zh_chs cookie |
| 输出 | JSON 已开启；HTML 保留给本地诊断 |
| 自动补全/favicon | 空字符串关闭；无需额外上游请求 |
| 页数 | max_page=1，配合现有 Cloud 至多5条候选；不是全网穷尽检索 |
| 安全过滤 | safe_search=1，保持原值 |
| HTTP | request_timeout=5、max_request_timeout=6、pool_connections=20、HTTP2=true |
| 403/验证码/429 | 暂停86400/86400/3600秒；不关闭上游拒绝暂停 |
| 重试 | 全局原值0；仅沿用已验证 Yahoo status0恢复一次，绝不重试403/429 |
| 服务 | 私有、limiter=false、image_proxy=false，原受控出口与证书/隔离不变 |

`docker/web-search/settings.yml` 为唯一操作者配置来源。Exa 显式注册也写入此文件，
其字典由离线检查与 zebra_exa.OPTIONAL_CONFIG 保持一致。
正常 Compose 与兼容 overlay 均读取 /etc/searxng/settings.yml；镜像 COPY 同一文件
作为无挂载时的默认值。不再维护第二份构建时拼装配置。
配置不是热加载：编辑后仍需要有计划地重建 Search 容器，但不必为 YAML 修改重建镜像。

## 验证与实际收益边界

先冻结四题，分别以 zh-CN/all 经正常 Worker HTTPS/native transport 调用，
次序 AB/BA/BA/AB；共8次 Yahoo 请求，0模型/0Exa请求，无错误、重试或有利替换。
题目为 Redis8新类型、PG18 AIO、中文 SQLite WAL、中文 Python3.14发布日期。

| 指标 | zh-CN | all |
| --- | --- | --- |
| 传输成功 |4/4|4/4|
| 指定官方目标 hit@5 |3/4|3/4|
| 端到端耗时中位数ms |1404.069|1149.376|

两个配置均未召回指定 Redis What's-new 页面；两者前三结果也相同，包含
Redis Cloud、Software 和 GitHub 开源版发布说明。因此不能说 all 修复了 Redis
来源召回，也不能把“指定目标未命中”说成完全没有官方可用来源。
样本少、源选择和缓存可能影响耗时；不宣称稳定提速或真实页面首正文收益。
采用 all 的理由是中英查询中立且当前样本无目标命中回退，不是已证实召回提升。

新镜像通过断网配置合并检查、Yahoo语言cookie检查、原有 Exa 持久冷却/lease/
回退/取消模拟检查，且四份网络与引擎源码摘要与正常旧镜像相同。
正常 Search 已按唯一配置路径更新，挂载/卷/证书/命令/权限原样保留；唯一环境
变化为 SEARXNG_SETTINGS_PATH。运行时读取值与宿主文件 SHA256 一致。
API/Worker 的 ID/镜像/启动时间/环境哈希均未变且健康。
上线后正常 Worker 默认调用两题（不再传 language 覆盖）：PG官方AIO1.869s、
SQLite官方WAL1.190s，目标均第一；无 Exa 调用或限流，无新模型请求。

本轮10次真实 Yahoo 请求。未运行模型页面，不声称 SQL/首正文新收益。
私有证据：.artifacts/cloud-searxng-config-01/{protocol.json,paired.json,
live-smoke.json,effective-settings.json,transport-hashes.json,after.json}。

## 运维命令

在仓库根目录执行：

```sh
docker build --platform linux/arm64 -t zebra-searxng:cloud-config-01 docker/web-search
docker run --rm --network none -e PYTHONPATH=/usr/local/searxng \
  -v "$PWD/docker/web-search:/checks:ro" \
  --entrypoint /usr/local/searxng/.venv/bin/python \
  zebra-searxng:cloud-config-01 /checks/check_config.py
docker run --rm --network none -e PYTHONPATH=/usr/local/searxng \
  -v "$PWD/docker/web-search:/checks:ro" \
  --entrypoint /usr/local/searxng/.venv/bin/python \
  zebra-searxng:cloud-config-01 /checks/check_exa.py
```

正常启动 `docker compose -f docker/web-search/compose.yml up -d` 使用新默认镜像/
配置路径。已有操作者出口环境覆盖应保留；不要用裸启动命令覆盖正在运行的出口。
本次实际激活先从 inspect 冻结当前配置，再只替换 Search 镜像及配置路径，
使用 --no-deps，不重启 Caddy、API、Worker，不改全局代理。
后续 YAML 修改重建 Search 时，也应保留持久卷和操作者环境。

回滚用旧 image ID（before.json）和旧 SEARXNG_SETTINGS_PATH=
/usr/local/searxng/zebra-exa-settings.yml，保留当前其余环境/挂载；旧镜像中原配置
副本仍在。没有清理旧镜像、卷或原始证据。

## 原 Exa 同进程观察结束

原搜索容器自2026-10-17 22:14:13运行至2026-10-18 01:19:16（上海时间）被本轮
已授权配置更新替换。替换前原会话仅有一次 initialize/initialized/tools-call，
无自然限流事件，所以没有同会话冷却恢复验收结果。
重建后旧内存会话不再存在；未尝试复活、探测或声称节省初始化请求。
持久冷却文件逐字保留、原 cache 卷保留、fast 与出口代码/配置不变。
依原观察任务终止条件，exa heartbeat 已删除，不再周期性探测额度。
未来首次正常业务显式选择 Exa 时可正常新建会话，但不计作原同进程恢复证明。
