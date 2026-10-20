"use client";

import React, { useState } from "react";

export interface AgentUsageCounts {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  reasoning_tokens: number;
  cache_hit_tokens: number;
  cache_miss_tokens: number;
  model_calls: number;
  unmetered_calls: number;
  tool_calls: number;
  messages: number;
}

export interface AgentUsageSnapshot {
  schema_version: 1;
  source: "committed_cloud_events";
  period: { days: 7 | 30; start: string; end: string; timezone: "UTC" };
  totals: AgentUsageCounts;
  daily: Array<{ date: string } & AgentUsageCounts>;
  daily_models: Array<{ date: string; model: string; model_calls: number; total_tokens: number }>;
  models: Array<{ model: string; model_calls: number; total_tokens: number }>;
  tools: Array<{ name: string; calls: number }>;
  tasks: Array<{ task_id: string; title: string } & AgentUsageCounts>;
}

export interface AgentUsageAnalyticsProps {
  snapshot: AgentUsageSnapshot | null;
  days: 7 | 30;
  onDaysChange: (days: 7 | 30) => void;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  taskHref?: (taskId: string) => string;
}

const number = (value: number) => new Intl.NumberFormat("zh-CN").format(value);
const dateLabel = (date: string) => date.slice(5).replace("-", "/");
const palette = ["#3478d4", "#ef9a52", "#62c978", "#e78ac2", "#a88de5"];

function Panel({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return <section className="zebra-usage-panel">
    <div className="zebra-usage-panel__intro"><h3>{title}</h3>{subtitle ? <p>{subtitle}</p> : null}</div>
    {children}
  </section>;
}

function HistoryChart({ daily }: { daily: AgentUsageSnapshot["daily"] }) {
  const max = Math.max(1, ...daily.map((day) => day.total_tokens));
  return <div className="zebra-usage-history" role="img" aria-label="每日输入和输出 Token 用量柱状图">
    <div className="zebra-usage-history__plot">
      {daily.map((day) => <div className="zebra-usage-history__column" key={day.date} title={`${day.date}: 输入 ${number(day.input_tokens)}，输出 ${number(day.output_tokens)}`}>
        <span className="zebra-usage-history__stack" style={{ height: `${Math.max(1, day.total_tokens / max * 100)}%` }}>
          <span style={{ height: `${day.total_tokens ? day.output_tokens / day.total_tokens * 100 : 0}%`, background: palette[1] }} />
          <span style={{ height: `${day.total_tokens ? day.input_tokens / day.total_tokens * 100 : 0}%`, background: palette[0] }} />
        </span>
      </div>)}
    </div>
    <div className="zebra-usage-history__axis"><span>{dateLabel(daily[0]?.date ?? "")}</span><span>{dateLabel(daily[Math.floor((daily.length - 1) / 2)]?.date ?? "")}</span><span>{dateLabel(daily[daily.length - 1]?.date ?? "")}</span></div>
    <div className="zebra-usage-legend"><span><i style={{ background: palette[0] }} />输入 Token</span><span><i style={{ background: palette[1] }} />输出 Token</span></div>
  </div>;
}

function ModelChart({ snapshot }: { snapshot: AgentUsageSnapshot }) {
  const models = snapshot.models.slice(0, 4);
  const max = Math.max(1, ...snapshot.daily_models.map((item) => item.model_calls));
  const width = 560;
  const height = 140;
  const days = snapshot.daily.map((item) => item.date);
  return <div className="zebra-usage-line" role="img" aria-label="按模型划分的每日消息调用次数折线图">
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
      {[0, 1, 2, 3].map((index) => <line key={index} x1="0" x2={width} y1={index * 45 + 2} y2={index * 45 + 2} stroke="currentColor" opacity=".12" />)}
      {models.map((model, index) => {
        const points = days.map((date, dayIndex) => {
          const count = snapshot.daily_models.find((item) => item.date === date && item.model === model.model)?.model_calls ?? 0;
          return `${days.length > 1 ? dayIndex / (days.length - 1) * width : width / 2},${height - count / max * (height - 12)}`;
        }).join(" ");
        return <polyline fill="none" key={model.model} points={points} stroke={palette[index]} strokeWidth="2.5" vectorEffect="non-scaling-stroke" />;
      })}
    </svg>
    <div className="zebra-usage-history__axis"><span>{dateLabel(days[0] ?? "")}</span><span>{dateLabel(days[days.length - 1] ?? "")}</span></div>
    <div className="zebra-usage-legend">{models.map((model, index) => <span key={model.model}><i style={{ background: palette[index] }} />{model.model}</span>)}</div>
  </div>;
}

function DailyActivityChart({ daily }: { daily: AgentUsageSnapshot["daily"] }) {
  const max = Math.max(1, ...daily.map((item) => item.tool_calls));
  const points = daily.map((item, index) => `${daily.length > 1 ? index / (daily.length - 1) * 560 : 280},${140 - item.tool_calls / max * 128}`).join(" ");
  return <div className="zebra-usage-line" role="img" aria-label="每日工具调用次数折线图">
    <svg viewBox="0 0 560 140" preserveAspectRatio="none" aria-hidden="true">
      {[0, 1, 2, 3].map((index) => <line key={index} x1="0" x2="560" y1={index * 45 + 2} y2={index * 45 + 2} stroke="currentColor" opacity=".12" />)}
      <polyline fill="none" points={points} stroke={palette[0]} strokeWidth="2.5" vectorEffect="non-scaling-stroke" />
    </svg>
    <div className="zebra-usage-history__axis"><span>{dateLabel(daily[0]?.date ?? "")}</span><span>{dateLabel(daily[daily.length - 1]?.date ?? "")}</span></div>
    <div className="zebra-usage-legend"><span><i style={{ background: palette[0] }} />工具调用</span></div>
  </div>;
}

export function AgentUsageAnalytics({ snapshot, days, onDaysChange, loading, error, onRetry, taskHref }: AgentUsageAnalyticsProps) {
  const [tab, setTab] = useState<"overview" | "analytics">("analytics");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const tasks = snapshot?.tasks ?? [];
  return <div className="zebra-usage">
    <div className="zebra-usage-tabs" role="tablist" aria-label="用量视图">
      <button aria-selected={tab === "overview"} onClick={() => setTab("overview")} role="tab" type="button">概览</button>
      <button aria-selected={tab === "analytics"} onClick={() => setTab("analytics")} role="tab" type="button">分析</button>
    </div>
    <div className="zebra-usage-heading"><div><h2>{tab === "analytics" ? "用量历史" : "Cloud Agent 用量"}</h2><p>当前账户的 Cloud Agent 用量。仅统计已提交的模型事件，按 UTC 日期汇总。</p></div><div className="zebra-usage-period" aria-label="统计区间"><button aria-pressed={days === 7} onClick={() => onDaysChange(7)} type="button">7天</button><button aria-pressed={days === 30} onClick={() => onDaysChange(30)} type="button">30天</button></div></div>
    {loading ? <p className="zebra-usage-state" role="status">正在加载用量…</p> : null}
    {error ? <div className="zebra-usage-state" role="alert">{error}{onRetry ? <button onClick={onRetry} type="button">重试</button> : null}</div> : null}
    {!loading && !error && snapshot ? <>
      {tab === "overview" ? <>
        <div className="zebra-usage-metrics"><Metric label="总 Token" value={snapshot.totals.total_tokens} /><Metric label="输入 Token" value={snapshot.totals.input_tokens} /><Metric label="输出 Token" value={snapshot.totals.output_tokens} /><Metric label="模型调用" value={snapshot.totals.model_calls} /></div>
        <Panel title="额度与计费" subtitle="Cloud Agent 当前只提供可审计的技术用量；套餐额度和积分由接入方计费系统定义。"><p className="zebra-usage-note">尚未配置额度和积分，暂不显示使用百分比或费用。</p></Panel>
        <Panel title="数据完整性"><p className="zebra-usage-note">{snapshot.totals.unmetered_calls ? `${number(snapshot.totals.unmetered_calls)} 次模型调用没有上游 Token 计量，不能视为零费用。` : "本时间窗口内没有缺失 Token 计量的模型调用。"} 推理 Token 是输出 Token 的子集，不重复计入总量。</p></Panel>
      </> : <>
        <div className="zebra-usage-chart-card"><HistoryChart daily={snapshot.daily} /><div className="zebra-usage-metrics zebra-usage-metrics--inside"><Metric label="总 Token" value={snapshot.totals.total_tokens} /><Metric label="输入 Token" value={snapshot.totals.input_tokens} /><Metric label="输出 Token" value={snapshot.totals.output_tokens} /><Metric label="缓存命中 Token" value={snapshot.totals.cache_hit_tokens} /></div></div>
        <Panel title="主要会话" subtitle="比较每个会话的模型用量；可展开查看输入、输出与调用次数。"><div className="zebra-usage-table-wrap"><table className="zebra-usage-table"><thead><tr><th>会话</th><th>Token</th><th>模型调用</th></tr></thead><tbody>{tasks.slice(0, showAll ? undefined : 5).map((task) => <tr key={task.task_id}><td><button aria-expanded={expanded === task.task_id} onClick={() => setExpanded(expanded === task.task_id ? null : task.task_id)} type="button">{expanded === task.task_id ? "⌄" : "›"} {task.title}</button>{expanded === task.task_id ? <div className="zebra-usage-task-detail">输入 {number(task.input_tokens)} · 输出 {number(task.output_tokens)} · 未计量调用 {number(task.unmetered_calls)}{taskHref ? <> · <a href={taskHref(task.task_id)}>打开会话</a></> : null}</div> : null}</td><td>{number(task.total_tokens)}</td><td>{number(task.model_calls)}</td></tr>)}</tbody></table>{!tasks.length ? <p className="zebra-usage-note">此区间暂无会话用量</p> : null}</div>{tasks.length > 5 ? <button className="zebra-usage-more" onClick={() => setShowAll(!showAll)} type="button">{showAll ? "收起" : "显示更多"}</button> : null}</Panel>
        <Panel title="计划使用历史" subtitle="参照套餐周额度展示；当前仅有技术用量，尚未配置套餐规则。"><div className="zebra-usage-table-wrap"><table className="zebra-usage-table"><thead><tr><th>时间段</th><th>Token</th><th>额度使用比例</th></tr></thead><tbody><tr><td>{snapshot.period.start} — {snapshot.period.end}</td><td>{number(snapshot.totals.total_tokens)}</td><td>—</td></tr></tbody></table></div><p className="zebra-usage-note">额度与积分暂不可用；接入计费规则后显示百分比。</p></Panel>
        <Panel title="模型用量" subtitle="按模型统计调用次数与 Token。"><div className="zebra-usage-table-wrap"><table className="zebra-usage-table"><thead><tr><th>模型</th><th>调用</th><th>Token</th></tr></thead><tbody>{snapshot.models.map((model) => <tr key={model.model}><td>{model.model}</td><td>{number(model.model_calls)}</td><td>{number(model.total_tokens)}</td></tr>)}</tbody></table>{!snapshot.models.length ? <p className="zebra-usage-note">此区间暂无模型用量</p> : null}</div></Panel>
        <Panel title="工具活动" subtitle="已提交的工具执行次数，按工具名称分组。"><div className="zebra-usage-metrics"><Metric label="工具调用" value={snapshot.totals.tool_calls} /></div><DailyActivityChart daily={snapshot.daily} /><div className="zebra-usage-tools">{snapshot.tools.slice(0, 10).map((tool) => <div key={tool.name}><span>{tool.name}</span><b>{number(tool.calls)}</b></div>)}{!snapshot.tools.length ? <p className="zebra-usage-note">此区间暂无工具活动</p> : null}</div></Panel>
        <Panel title="技能使用" subtitle="与 Codex 分析页保持相同的信息位置。"><p className="zebra-usage-note">Cloud Agent 尚未记录独立的技能调用计量事件，暂不展示推测值。</p></Panel>
        <Panel title="消息" subtitle="按模型查看每日调用走势；用户发送消息数与模型调用次数分开统计。"><div className="zebra-usage-metrics"><Metric label="用户消息" value={snapshot.totals.messages} /><Metric label="模型调用" value={snapshot.totals.model_calls} /></div><ModelChart snapshot={snapshot} /></Panel>
      </>}
    </> : null}
  </div>;
}

function Metric({ label, value }: { label: string; value: number }) {
  return <div className="zebra-usage-metric"><span>{label}</span><strong>{number(value)}</strong></div>;
}
