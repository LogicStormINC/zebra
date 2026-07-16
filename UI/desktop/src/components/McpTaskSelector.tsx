import { Checkbox } from "antd";
import { availableMcpToolNames } from "../lib/mcp-capabilities";
import type { McpCapabilitiesResponse } from "../types";

interface McpTaskSelectorProps {
  capabilities: McpCapabilitiesResponse | undefined;
  busy: boolean;
  errorText: string | null;
  className: string;
  selected: string[];
  onChange: (selected: string[]) => void;
}

export function McpTaskSelector({
  capabilities,
  busy,
  errorText,
  className,
  selected,
  onChange,
}: McpTaskSelectorProps) {
  const available = availableMcpToolNames(capabilities);
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
          value={selected}
          onChange={(values) => onChange(values.map(String).sort())}
        />
      ) : null}
      <span>只选择当前任务真正需要的工具；实际调用仍需逐次批准。</span>
    </div>
  );
}
