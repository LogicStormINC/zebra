import React, { useEffect, useState } from 'react';
import { approvalDiff, approvalFieldLabel, displayValue, operationLabel, proposalArguments, safeError } from './workbench-state.mjs';

function Review({ proposal, api, confirming, onConfirm }: any) {
  const args = proposalArguments(proposal), [current, setCurrent] = useState<any>(null), [reading, setReading] = useState(false), [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    setCurrent(null); setError('');
    if (proposal.operation === 'create' || !args.doctype || !args.name) return;
    setReading(true);
    api('zebra_erpnext.business.execute', {operation:'get',arguments:JSON.stringify({doctype:args.doctype,name:args.name,...(args.company || proposal.company ? {company:args.company || proposal.company} : {})}),request_id:crypto.randomUUID()})
      .then((value:any) => { if (alive) setCurrent(value); }).catch((error:any) => { if (alive) setError(safeError(error)); }).finally(() => { if (alive) setReading(false); });
    return () => { alive = false; };
  }, [proposal.name]);
  const values = args.values || (proposal.operation === 'submit' ? {docstatus:1} : proposal.operation === 'cancel' ? {docstatus:2} : proposal.operation === 'delete' ? {name:'删除单据'} : {});
  const rows = approvalDiff(values,current);
  return <section className="ze-review">
    <p className="ze-eyebrow">REVIEW BEFORE EXECUTION</p><h2>{operationLabel(proposal.operation)}</h2>
    <p className="ze-review-intro">请核对实际范围。只有点击下方确认，才会执行这项操作。</p>
    <div className="ze-review-target"><strong>{args.doctype || '业务操作'}{args.name ? ` / ${args.name}` : ' · 新建'}</strong><small>{proposal.company || args.company || '公司未提供'}</small></div>
    {reading && <p role="status">正在读取当前单据…</p>}
    {error && <p className="ze-review-warning">当前值未知：{error}</p>}
    {proposal.operation === 'create' && <p className="ze-review-warning">创建新的草稿；尚无可比较的当前单据。</p>}
    {current && args.modified && current.modified !== args.modified && <p className="ze-review-warning">单据已变化；下面是当前读取值，服务器会按原审批版本再次校验。</p>}
    {rows.length > 0 ? <div className="ze-diff-scroll"><table className="ze-diff"><thead><tr><th>字段 / 行</th><th>当前读取值</th><th>拟执行变更</th></tr></thead><tbody>{rows.map((row:any,index:number) => <tr key={index}><th title={row.field}>{approvalFieldLabel(row.field,args.doctype,(doctype:any) => window.frappe.get_meta?.(doctype))}{row.kind === 'reordered' ? ' · 行顺序' : row.kind === 'removed' ? ' · 删除' : row.kind === 'added' ? ' · 新增' : ''}</th><td>{displayValue(row.before)}</td><td>{displayValue(row.after)}</td></tr>)}</tbody></table></div> : <p className="ze-review-warning">{args.values ? '已读取字段与拟写入值一致。' : '此操作没有字段级预览；请核对下方准确参数。'}</p>}
    <p className="ze-review-scope">当前值仅代表本次权限范围内的读取。未读取、缺少或不可读的字段均为未知；确认参数保持原样。</p>
    <details className="ze-review-raw"><summary>查看准确操作参数</summary><pre>{JSON.stringify({operation:proposal.operation,arguments:args},null,2)}</pre></details>
    <button className="ze-confirm" disabled={!!confirming || reading} onClick={() => onConfirm(proposal)}>{confirming === proposal.name ? '正在等待服务器结果…' : `确认并${operationLabel(proposal.operation)}`}</button>
  </section>;
}
export function Approvals({ proposals, api, confirming, onConfirm }: any) {
  return <div className="ze-approvals">{proposals.length ? proposals.map((proposal:any) => <Review key={proposal.name} {...{proposal,api,confirming,onConfirm}} />) : <div className="ze-drawer-empty"><h2>暂无待确认操作</h2><p>需要变更业务数据时，操作范围会显示在这里。</p></div>}</div>;
}
