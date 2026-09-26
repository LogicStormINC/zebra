import type { CSSProperties } from "react";

/** Host-controlled visual tokens shared by AgentChat and AgentComposer. */
export interface AgentThemeTokens {
  accent: string;
  accentText: string;
  border: string;
  composerRadius: string;
  contentWidth: string;
  draftWidth: string;
  faint: string;
  fontFamily: string;
  hover: string;
  input: string;
  muted: string;
  surface: string;
  surfaceRaised: string;
  text: string;
  userBubbleRadius: string;
  wideContentWidth: string;
}

const tokenVariables: Record<keyof AgentThemeTokens, `--zebra-agent-${string}`> = {
  accent: "--zebra-agent-accent",
  accentText: "--zebra-agent-accent-text",
  border: "--zebra-agent-border",
  composerRadius: "--zebra-agent-composer-radius",
  contentWidth: "--zebra-agent-content-width",
  draftWidth: "--zebra-agent-draft-width",
  faint: "--zebra-agent-faint",
  fontFamily: "--zebra-agent-font-family",
  hover: "--zebra-agent-hover",
  input: "--zebra-agent-input",
  muted: "--zebra-agent-muted",
  surface: "--zebra-agent-surface",
  surfaceRaised: "--zebra-agent-surface-raised",
  text: "--zebra-agent-text",
  userBubbleRadius: "--zebra-agent-user-bubble-radius",
  wideContentWidth: "--zebra-agent-wide-content-width",
};

export function createAgentThemeStyle(tokens?: Partial<AgentThemeTokens>): CSSProperties | undefined {
  if (!tokens) return undefined;
  const style: Record<string, string> = {};
  for (const key of Object.keys(tokens) as (keyof AgentThemeTokens)[]) {
    const value = tokens[key];
    if (value !== undefined) style[tokenVariables[key]] = value;
  }
  return style as CSSProperties;
}
