export interface AssistantInsights {
  commands: string[];
  files: string[];
  statuses: string[];
}

const FILE_PATTERN = /\b(?:apps|packages|tests|docs|UI)\/[A-Za-z0-9_./-]+\.[A-Za-z0-9_-]+\b/g;
const INLINE_CODE_PATTERN = /`([^`]+)`/g;

function unique(values: string[]) {
  return [...new Set(values)];
}

function looksLikeCommand(value: string) {
  return (
    value.startsWith("make ") ||
    value.startsWith("pnpm ") ||
    value.startsWith("uv ") ||
    value.startsWith("cd ") ||
    value.startsWith("pytest ") ||
    value.startsWith("ruff ") ||
    value.startsWith("mypy ")
  );
}

export function extractAssistantInsights(content: string): AssistantInsights {
  const files = unique(content.match(FILE_PATTERN) ?? []).slice(0, 4);

  const inlineCodes = Array.from(content.matchAll(INLINE_CODE_PATTERN))
    .map((match) => match[1].trim())
    .filter(Boolean);
  const commands = unique(inlineCodes.filter(looksLikeCommand)).slice(0, 3);

  const statuses = unique(
    content
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => {
        if (!line) {
          return false;
        }
        return (
          line.includes("通过") ||
          line.includes("已完成") ||
          line.includes("passed") ||
          line.includes("409") ||
          line.includes("201") ||
          line.includes("204")
        );
      }),
  ).slice(0, 3);

  return { commands, files, statuses };
}
