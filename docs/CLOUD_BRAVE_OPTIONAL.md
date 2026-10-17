# Brave 可选接入已取消

2026-10-17，用户明确放弃 Brave；此前准备提交 445fa13f 未激活。
已移除 prepare_brave.py、check_brave.py 和 compose.brave.yml。
不再申请或配置 Brave 密钥；私有目录若已有操作者文件，不读取或删除。
正常 Yahoo settings/Compose/Dockerfile、API/Worker/Search 服务均不改。
原离线检查不构成任何搜索召回/延迟验收，未执行真实 Brave 查询。
后续以用户优先免密钥要求执行，见 [替代路线](CLOUD_SEARCH_ALTERNATIVES.md)。
