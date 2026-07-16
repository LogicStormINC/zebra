import { ReloadOutlined } from "@ant-design/icons";
import { Button, Input, Select } from "antd";
import { availableMcpPrompts } from "../lib/mcp-capabilities";
import { mcpPromptSchema } from "../lib/task-launch-config";
import type { McpPromptsResponse } from "../types";
import { useMcpPromptSelectorStyle } from "./McpPromptSelector.styles";

interface McpPromptSelectorProps {
  arguments: Record<string, string>;
  busy: boolean;
  data: McpPromptsResponse | undefined;
  errorText: string | null;
  selectedPromptId: string | null;
  onArgumentsChange: (argumentsValue: Record<string, string>) => void;
  onRefresh: () => void;
  onSelectionChange: (promptId: string | null, schema: string | null) => void;
}

const byteLength = (value: string) => new TextEncoder().encode(value).byteLength;

export function McpPromptSelector(props: McpPromptSelectorProps) {
  const { styles } = useMcpPromptSelectorStyle();
  const prompts = props.errorText ? [] : availableMcpPrompts(props.data);
  const selected = prompts.find((prompt) => prompt.prompt_id === props.selectedPromptId);
  const unavailable = props.data?.status === "unavailable" || Boolean(props.errorText);
  const untouched = !props.data && !props.errorText && !props.busy;

  const updateArgument = (name: string, value: string, required: boolean) => {
    const next = { ...props.arguments };
    if (!required && !value) delete next[name];
    else next[name] = value;
    props.onArgumentsChange(next);
  };

  return (
    <section aria-label="MCP Prompt 模板" className={styles.root}>
      <div className={styles.header}>
        <strong>创建任务时使用的 Prompt</strong>
        <Button
          aria-label="刷新 MCP Prompt 清单"
          icon={<ReloadOutlined />}
          loading={props.busy}
          onClick={props.onRefresh}
          size="small"
          type="text"
        >
          刷新
        </Button>
      </div>
      {props.busy ? <p aria-live="polite" className={styles.state}>正在读取安全 Prompt 清单…</p> : null}
      {unavailable ? (
        <p className={styles.error} role="alert">{props.errorText ?? props.data?.reason ?? "MCP Prompt 当前不可用。"}</p>
      ) : null}
      {untouched ? <p className={styles.state}>仅在点击刷新时读取清单，不会后台轮询。</p> : null}
      {!props.busy && !unavailable && props.data && prompts.length === 0 ? (
        <p className={styles.state}>当前没有可用 Prompt 模板。</p>
      ) : null}
      {prompts.length > 0 ? (
        <Select
          allowClear
          aria-label="选择 MCP Prompt"
          onChange={(promptId?: string) => {
            const prompt = prompts.find((item) => item.prompt_id === promptId);
            props.onSelectionChange(prompt?.prompt_id ?? null, prompt ? mcpPromptSchema(prompt) : null);
          }}
          options={prompts.map((prompt) => ({ label: prompt.name, value: prompt.prompt_id }))}
          placeholder="选择一个 Prompt"
          value={selected?.prompt_id}
        />
      ) : null}
      {props.selectedPromptId && !selected ? (
        <div className={styles.restored}>
          <span className={styles.state}>已从本地恢复选择；刷新后确认可用性。</span>
          <code title={props.selectedPromptId}>{props.selectedPromptId}</code>
        </div>
      ) : null}
      {selected ? (
        <div className={styles.selected}>
          <p className={styles.description}>{selected.description || "此 Prompt 未提供说明。"}</p>
          {selected.arguments.length === 0 ? <p className={styles.state}>无需填写参数。</p> : null}
          {selected.arguments.map((argument) => {
            const value = props.arguments[argument.name] ?? "";
            return (
              <div className={styles.field} key={argument.name}>
                <label htmlFor={`mcp-prompt-${argument.name}`}>
                  <span>{argument.name}{argument.required ? " · 必填" : " · 可选"}</span>
                  <small>{byteLength(value)} / 4096 B</small>
                </label>
                <Input
                  aria-describedby={argument.description ? `mcp-prompt-${argument.name}-help` : undefined}
                  id={`mcp-prompt-${argument.name}`}
                  onChange={(event) => updateArgument(argument.name, event.target.value, argument.required)}
                  placeholder={argument.description || argument.name}
                  status={argument.required && !value.trim() ? "error" : undefined}
                  value={value}
                />
                {argument.description ? <small id={`mcp-prompt-${argument.name}-help`}>{argument.description}</small> : null}
              </div>
            );
          })}
          <p className={styles.state}>模板仅在创建任务时解析一次，保存后不会自动刷新或重新执行。</p>
        </div>
      ) : null}
    </section>
  );
}
