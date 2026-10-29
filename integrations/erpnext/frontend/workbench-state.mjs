export const isActive = status => ['ready', 'created', 'dispatching', 'running', 'queued', 'accepted', 'waiting', 'waiting_client_effect', 'submitting'].includes(status);
export const isCurrentView = (source, epoch, current, currentEpoch) => source === current && epoch === currentEpoch;
export const UNKNOWN = Symbol('unknown');
export function rpcMethod(method) {
  const path = method.includes('.') ? method : `zebra_erpnext.api.${method}`;
  if (!/^zebra_erpnext\.(api\.[a-z][a-z_]*|business\.(execute|confirm))$/.test(path)) throw new Error('请求方法无效');
  return path;
}
export const safeError = error => String(error instanceof Error ? error.message : '请求失败').replace(/[\x00-\x1f\x7f]/g, ' ').slice(0, 240);
export function proposalArguments(proposal) {
  try { const args = typeof proposal.arguments_json === 'string' ? JSON.parse(proposal.arguments_json) : proposal.arguments_json || proposal.arguments; return args && typeof args === 'object' && !Array.isArray(args) ? args : {}; } catch { return {}; }
}
// ponytail: compare only proposed writable fields; absent permission-filtered fields
// remain unknown. Named child rows keep their identity across deletion and reordering.
export function approvalDiff(values, current, prefix = '') {
  const rows = [];
  for (const [key, after] of Object.entries(values || {})) {
    const field = prefix + key;
    const before = current && Object.hasOwn(current, key) ? current[key] : UNKNOWN;
    if (Array.isArray(after) && Array.isArray(before) && after.every(row => row && typeof row === 'object') && before.every(row => row && typeof row === 'object')) {
      const names = after.map(row => row.name).filter(Boolean), oldNames = before.map(row => row.name).filter(Boolean);
      const retained = oldNames.filter(name => names.includes(name));
      if (JSON.stringify(retained) !== JSON.stringify(names.filter(name => oldNames.includes(name)))) rows.push({field, before:oldNames, after:names, kind:'reordered'});
      for (const row of before) if (row.name && !names.includes(row.name)) rows.push({field:`${field}[${row.name}]`, before:row, after:'移除整行', kind:'removed'});
      after.forEach((row, index) => {
        const original = row.name ? before.find(value => value.name === row.name) : null;
        const {name, ...changes} = row;
        if (!original) rows.push({field:`${field}[新增 ${index + 1}]`, before:UNKNOWN, after:row, kind:'added'});
        else rows.push(...approvalDiff(changes, original, `${field}[${name}].`));
      });
    } else if (before === UNKNOWN || JSON.stringify(before) !== JSON.stringify(after)) rows.push({field,before,after,kind:'changed'});
  }
  return rows;
}
export const displayValue = value => value === UNKNOWN ? '未知（未读取或无字段权限）' : value === undefined ? '未提供' : value === null ? '空值' : typeof value === 'object' ? JSON.stringify(value) : String(value);
export const operationLabel = operation => ({create:'创建草稿',update:'保存草稿变更',settings_update:'更新设置',submit:'提交单据',cancel:'取消单据',delete:'删除单据',amend:'创建修订草稿',workflow:'执行工作流',comment:'添加评论',action:'执行单据动作',create_from_action:'转换单据',upload_file:'上传附件',attach_file:'关联附件',remove_file:'移除附件'})[operation] || '执行此操作';
export function confirmationReceipt(result) {
  const doc = result?.document && typeof result.document === 'object' ? result.document : result;
  const label = result?.deleted === true ? '单据已删除' : result?.saved === false ? '已生成未保存草稿' : doc?.docstatus === 0 ? '已保存草稿' : doc?.docstatus === 1 ? '单据已提交' : doc?.docstatus === 2 ? '单据已取消' : '服务器已返回操作结果，请核对单据';
  return {label, ...(typeof doc?.doctype === 'string' && typeof doc?.name === 'string' && result?.saved !== false ? {doctype:doc.doctype.slice(0,140),name:doc.name.slice(0,140)} : {})};
}

const fieldLabels = {planned_qty:'计划数量',docstatus:'单据状态',name:'单据编号',items:'明细',po_items:'生产计划明细',qty:'数量',item_code:'产品',warehouse:'仓库',schedule_date:'计划日期',company:'公司'};
export function approvalFieldLabel(path, doctype, metaFor = () => null) {
  const match = /^([^.[\]]+)(?:\[([^\]]+)\])?(?:\.(.+))?$/.exec(path);
  if (!match) return path;
  const [,field,row,child] = match;
  let meta;
  try { meta = metaFor(doctype)?.fields?.find(value => value.fieldname === field); } catch { /* Cached native metadata is optional. */ }
  const label = meta?.label || fieldLabels[field] || field;
  return `${label}${row ? ` · ${row}` : ''}${child ? ` / ${approvalFieldLabel(child,meta?.options,metaFor)}` : ''}`;
}
