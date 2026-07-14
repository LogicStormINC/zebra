import { CodeOutlined } from "@ant-design/icons";
import { createStyles } from "antd-style";
import { clsx } from "clsx";
import locale from "../_utils/local";
import { compactWorkspaceLabel } from "../lib/task-launch-config";
import type { WorkspaceProject } from "../lib/workspace-projects";

const useStyle = createStyles(({ css }) => ({
  section: css`margin-top: var(--zebra-space-xs); min-width: 0;`,
  title: css`
    padding: var(--zebra-space-xs) var(--zebra-space-sm) calc(var(--zebra-space-xs) - var(--zebra-space-3xs));
    color: var(--zebra-text-subtle);
    font-size: 12px;
    line-height: 18px;
    font-weight: var(--zebra-font-weight-medium);
    letter-spacing: 0.05em;
    text-transform: uppercase;
    @media (max-width: 767px) { display: none; }
  `,
  list: css`display: flex; flex-direction: column; gap: var(--zebra-space-2xs);`,
  card: css`
    width: 100%;
    display: flex;
    align-items: center;
    gap: var(--zebra-space-xs);
    padding: var(--zebra-space-sm);
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--zebra-surface-border-soft);
    color: var(--zebra-text-primary);
    font: inherit;
    text-align: left;
    cursor: pointer;
    transition: background 160ms ease, border-color 160ms ease;
    &:hover { background: rgba(255, 255, 255, 0.055); }
    @media (max-width: 767px) { justify-content: center; padding: var(--zebra-space-xs); }
  `,
  active: css`background: rgba(255, 255, 255, 0.075); border-color: transparent;`,
  icon: css`
    width: var(--zebra-icon-size-sm);
    height: var(--zebra-icon-size-sm);
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: var(--zebra-radius-xs);
    background: rgba(242, 140, 56, 0.16);
    color: #ffbc82;
    font-size: var(--zebra-font-size-md);
  `,
  meta: css`
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: var(--zebra-space-3xs);
    span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    span:last-child { color: var(--zebra-text-subtle); font-size: 12px; line-height: 18px; }
    @media (max-width: 767px) { display: none; }
  `,
}));

export function WorkspaceProjectSection({
  onSelectProject,
  projects,
  selectedProjectId,
}: {
  onSelectProject: (project: WorkspaceProject) => void;
  projects: WorkspaceProject[];
  selectedProjectId: string;
}) {
  const { styles } = useStyle();
  return (
    <section className={styles.section}>
      <div className={styles.title}>{locale.projects}</div>
      <div className={styles.list}>
        {projects.map((project) => {
          const label = project.workspaceRoot
            ? compactWorkspaceLabel(project.workspaceRoot)
            : locale.unboundProject;
          const target = project.configured ? `${locale.newTaskTarget} · ` : "";
          return (
            <button
              aria-pressed={project.id === selectedProjectId}
              className={clsx(styles.card, project.id === selectedProjectId && styles.active)}
              key={project.id}
              onClick={() => onSelectProject(project)}
              title={project.workspaceRoot ?? locale.workspaceUnbound}
              type="button"
            >
              <span className={styles.icon}><CodeOutlined /></span>
              <span className={styles.meta}>
                <span>{label}</span>
                <span>{target}{project.conversationKeys.length} {locale.tasks}</span>
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
