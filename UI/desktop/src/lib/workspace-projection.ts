export function projectWorkspaceLabel(workspaceRoot: string | undefined, unavailableLabel: string): string {
  const parts = workspaceRoot?.split(/[\\/]/).filter(Boolean);
  return parts?.[parts.length - 1] ?? unavailableLabel;
}
