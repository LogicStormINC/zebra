import type { McpCapabilitiesResponse } from "../types";

export type McpCapabilityState = "checking" | "available" | "unconfigured" | "unavailable";

export interface McpCapabilityView {
  state: McpCapabilityState;
  label: string;
  color: string;
  summary: string;
}

export function projectMcpCapabilities(
  data: McpCapabilitiesResponse | undefined,
  isFetching: boolean,
  errorText: string | null,
): McpCapabilityView {
  if (isFetching) {
    return { state: "checking", label: "检查中", color: "gold", summary: "正在读取 MCP 能力清单。" };
  }
  if (errorText) {
    return { state: "unavailable", label: "不可用", color: "red", summary: errorText };
  }
  if (data?.status === "available") {
    return {
      state: "available",
      label: "可用",
      color: "green",
      summary: `${data.server_count} 个服务器，${data.tool_count} 个工具`,
    };
  }
  if (data?.status === "unconfigured") {
    return { state: "unconfigured", label: "未配置", color: "default", summary: "当前未配置 MCP 服务器。" };
  }
  return { state: "unavailable", label: "不可用", color: "red", summary: "等待运行时连接。" };
}
