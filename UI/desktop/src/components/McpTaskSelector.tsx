import { Checkbox } from "antd";
import { availableMcpToolNames } from "../lib/mcp-capabilities";
import type { McpCapabilitiesResponse } from "../types";

interface McpTaskSelectorProps {
  capabilities: McpCapabilitiesResponse | undefined;
  busy: boolean;
  errorText: string | null;
  className: string;
  selectedTools: string[];
  selectedResources: string[];
  onToolsChange: (selected: string[]) => void;
  onResourcesChange: (selected: string[]) => void;
}

export function McpTaskSelector({
  capabilities,
  busy,
  errorText,
  className,
  selectedTools,
  selectedResources,
  onToolsChange,
  onResourcesChange,
}: McpTaskSelectorProps) {
  const available = availableMcpToolNames(capabilities);
  const resources = capabilities?.status === "available"
    ? capabilities.servers.flatMap((server) => (server.resources ?? []).map((resource) => ({ ...resource, server: server.name })))
    : [];
  return (
    <div className={className}>
      <strong>此任务可使用的 MCP 工具</strong>
      {busy ? <span>正在读取安全能力清单…</span> : null}
      {errorText ? <span>{errorText}</span> : null}
      {!busy && !errorText && available.length === 0 ? (
        <span>当前没有可用 MCP 工具，请先在运行配置中检查服务。</span>
      ) : null}
      {available.length > 0 ? (
        <Checkbox.Group
          options={available.map((name) => ({ label: name.slice(4), value: name }))}
          value={selectedTools}
          onChange={(values) => onToolsChange(values.map(String).sort())}
        />
      ) : null}
      <span>只选择当前任务真正需要的工具；实际调用仍需逐次批准。</span>
      <strong>创建任务时读取的 MCP 资源</strong>
      {resources.length === 0 ? <span>当前没有可用的文本资源。</span> : (
        <Checkbox.Group
          options={resources.map((resource) => ({
            label: `${resource.server} · ${resource.name}`,
            value: resource.resource_id,
          }))}
          value={selectedResources}
          onChange={(values) => onResourcesChange(values.map(String).sort())}
        />
      )}
      <span>最多 4 项；创建任务时读取一次并作为不可信材料持久化，运行中不会自动刷新。</span>
    </div>
  );
}
