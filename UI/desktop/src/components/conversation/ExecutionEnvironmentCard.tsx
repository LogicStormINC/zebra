import { FolderOpenOutlined, GlobalOutlined, SafetyOutlined, ToolOutlined } from "@ant-design/icons";
import React from "react";
import locale from "../../_utils/local";
import { compactWorkspaceLabel, taskNetworkProfileLabel, type TaskLaunchConfig } from "../../lib/task-launch-config";
import { useConversationPaneStyle } from "../CodexConversationPane.styles";

interface ExecutionEnvironmentCardProps {
  config: TaskLaunchConfig;
  editable: boolean;
  errorText?: string | null;
}

export function ExecutionEnvironmentCard({ config, editable, errorText }: ExecutionEnvironmentCardProps) {
  const { styles } = useConversationPaneStyle();
  const cells: Array<{ key: string; icon: React.ReactNode; label: string; value: string; title?: string }> = [
    {
      key: "workspace",
      icon: <FolderOpenOutlined />,
      label: locale.envWorkspace,
      value: compactWorkspaceLabel(config.workspace),
      title: config.workspace || undefined,
    },
    {
      key: "permission",
      icon: <SafetyOutlined />,
      label: locale.envPermission,
      value: config.policyProfile === "full_access" ? locale.envAccessFull : locale.envAccessWrite,
    },
    {
      key: "capability",
      icon: <ToolOutlined />,
      label: locale.envCapability,
      value: config.toolProfile === "coding" ? locale.envToolCoding : locale.envToolGeneral,
    },
    {
      key: "network",
      icon: <GlobalOutlined />,
      label: locale.envNetwork,
      value: taskNetworkProfileLabel(config.networkProfile),
    },
  ];

  return (
    <div className={styles.envCard} role="group" aria-label={locale.executionEnvironment}>
      <div className={styles.envCardHeader}>
        <span className={styles.envCardTitle}>{locale.executionEnvironment}</span>
        {editable ? null : <span className={styles.envCardMeta}>{locale.envLockedHint}</span>}
      </div>
      <div className={styles.envGrid}>
        {cells.map((cell) => (
          <div className={styles.envCell} key={cell.key}>
            <span className={styles.envCellIcon}>{cell.icon}</span>
            <span className={styles.envCellBody}>
              <span className={styles.envCellLabel}>{cell.label}</span>
              <span className={styles.envCellValue} title={cell.title}>{cell.value}</span>
            </span>
          </div>
        ))}
      </div>
      {errorText ? <div className={styles.envError} role="alert">{errorText}</div> : null}
    </div>
  );
}

export function ExecutionEnvironmentHint({ config }: { config: TaskLaunchConfig }) {
  const { styles } = useConversationPaneStyle();
  return (
    <div className={styles.envHint} role="group" aria-label={locale.executionEnvironment}>
      <span title={config.workspace || undefined}>
        <FolderOpenOutlined />
        {locale.envWorkspace} · <b>{compactWorkspaceLabel(config.workspace)}</b>
      </span>
      <span>
        <SafetyOutlined />
        {locale.envPermission} · <b>{config.policyProfile === "full_access" ? locale.envAccessFull : locale.envAccessWrite}</b>
      </span>
      <span>
        <ToolOutlined />
        {locale.envCapability} · <b>{config.toolProfile === "coding" ? locale.envToolCoding : locale.envToolGeneral}</b>
      </span>
      <span>
        <GlobalOutlined />
        {locale.envNetwork} · <b>{taskNetworkProfileLabel(config.networkProfile)}</b>
      </span>
    </div>
  );
}
