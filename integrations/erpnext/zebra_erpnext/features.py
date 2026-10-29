"""Honest capability availability; never expose operator configuration or credentials."""
import frappe
from zebra_erpnext import cloud, runtime


def catalog(conversation=None):
    cloud.principal()
    doc = cloud.owned(conversation) if conversation else None
    private = cloud.has_private_workspace(doc) if doc else True
    full = bool(doc and runtime.release(doc) == runtime.FULL)
    settings = runtime.settings(doc, cloud.config()) if doc else cloud.config()
    uploads_enabled = (runtime.enabled(doc, cloud.config(), 'attachments') if full
                       else settings.get("attachments_enabled") is True)
    runtime_probe = {"status": "not_checked", "network_profiles": []}
    if doc:
        try:
            probe = cloud.request(doc, "GET", "/capabilities/runtime", run_id=doc.active_run_id)
            runtime_probe = {"status": "available", "contract_version": probe.get("contract_version"),
                       "network_profiles": probe.get("network_profiles", []),
                       "client_surface_contract_version": probe.get("client_surface_contract_version")}
        except Exception:
            runtime_probe = {"status": "unavailable", "network_profiles": [], "reason": "暂时无法核验 Cloud 能力，请重试"}
    groups = [
        {"id": "erp", "label": "ERPNext 业务", "status": "partial",
         "reason": "已接入权限感知的通用业务操作；模块专用动作按覆盖清单逐项验收"},
        {"id": "attachments", "label": "上传文件与图片", "status": "available" if private and uploads_enabled else "unavailable",
         "reason": ("新会话使用用户与公司隔离的文件空间" if uploads_enabled else "此旧版会话不支持上传，请新建已升级会话") if private else "旧会话绑定共享工作区，请新建会话上传私人资料"},
        {"id": "artifacts", "label": "成果与用量", "status": "available",
         "reason": "按当前授权任务读取成果、附件与模型用量；历史分段资源范围单独标明"},
        {"id": "web", "label": "联网与分析", "status": "pending",
         "reason": "当前任务仍使用受限网络配置，待原生能力与出网授权验收"},
        {"id": "extensions", "label": "技能与 MCP", "status": "pending",
         "reason": "待接入当前用户授权的技能和连接；选择不能提升服务端权限"},
        {"id": "knowledge", "label": "知识资料与记忆", "status": "pending",
         "reason": "待验证用户、公司与资料权限隔离后开放"},
        {"id": "schedules", "label": "定时任务", "status": "pending",
         "reason": "待开通原生调度授权和每次触发时的权限复核"},
    ]
    if full:
        flags = settings.get('capabilities') or {}
        descriptions = {
            'web': '由当前会话已授权的固定能力组合控制；联网工具仍逐次检查出网策略',
            'extensions': '选择已启用的 Skill 与 MCP；安装目录与本轮授权由 Native 核验',
            'knowledge': '私人资料按用户和公司隔离；可选择随下一条消息发送，记忆按工作区管理',
            'schedules': '由 Native 调度器执行；每次触发重新检查用户与公司权限',
        }
        for group in groups:
            key = group['id']
            if key in descriptions:
                group.update(status='available' if flags.get(key) is True else 'unavailable',
                             reason=descriptions[key] if flags.get(key) is True else '此运行时尚未开放该能力')
    if doc and runtime_probe['status'] != 'available':
        for group in groups:
            if group['status'] == 'available':
                group.update(status='pending', reason='当前无法核验运行时；恢复连接后可继续使用原任务')
        uploads_enabled = False
    return {"runtime_release": runtime.release(doc) if doc else runtime.new_release(settings),
            "capability_profile": runtime.preferences(doc).get('capability_profile', 'business') if doc else 'business',
            "capability_profiles": [key for key in runtime.PROFILES if key in settings.get('capability_profiles', ['business'])],
            "extension_selection": runtime.selections(doc) if full else {},
            "capabilities_locked": bool(doc and (doc.task_id or doc.pending_command)),
            "groups": groups, "private_uploads": private and uploads_enabled, "legacy_workspace": bool(doc and not private),
            "attachment_limits": {"count": 4, "text_bytes": 65536,
                                  "document_bytes": 4194304, "image_bytes": 16777216},
            "runtime": runtime_probe}
