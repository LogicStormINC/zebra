import type {
  ArtifactSummary,
  DeliveryAuditRecord,
  SessionArtifactsResponse,
  SessionDeliveryAuditResponse,
  SessionDiffResponse,
} from "../types";

export function decodeArtifactContent(contentBase64: string) {
  const binary = window.atob(contentBase64);
  return new TextDecoder().decode(Uint8Array.from(binary, (char) => char.charCodeAt(0)));
}

export interface SessionResultSurface {
  diff: SessionDiffResponse | null;
  artifacts: SessionArtifactsResponse | null;
  deliveryAudit: SessionDeliveryAuditResponse | null;
}

export type SessionResultFocus =
  | { kind: "file"; path: string }
  | { kind: "artifact"; artifactId: string }
  | { kind: "delivery"; index: number };

export interface ChangedFileSummary {
  path: string;
  status: string;
}

export function extractDiffChunk(diff: SessionDiffResponse | null, path: string): string {
  if (!diff?.diff.trim()) {
    return "";
  }

  const sections = diff.diff.split(/^diff --git /gm).filter(Boolean);
  for (const section of sections) {
    const normalizedSection = `diff --git ${section}`;
    const match = normalizedSection.match(/^diff --git a\/(.+?) b\/(.+)$/m);
    if (!match) {
      continue;
    }
    const beforePath = match[1] ?? "";
    const afterPath = match[2] ?? "";
    if (beforePath === path || afterPath === path) {
      return normalizedSection;
    }
  }

  return diff.diff;
}

export function extractChangedFiles(diff: SessionDiffResponse | null): ChangedFileSummary[] {
  if (!diff) {
    return [];
  }

  const statusLines = diff.git_status
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (statusLines.length > 0) {
    return statusLines.slice(0, 6).map((line) => {
      const status = line.slice(0, 2).trim() || "M";
      const path = line.slice(2).trim() || line;
      return { status, path };
    });
  }

  const diffHeaders = Array.from(diff.diff.matchAll(/^diff --git a\/(.+?) b\/(.+)$/gm)).slice(0, 6);
  return diffHeaders.map((match) => ({
    status: "M",
    path: match[2] ?? match[1] ?? "",
  }));
}

export function summarizeArtifacts(artifacts: SessionArtifactsResponse | null): ArtifactSummary[] {
  return (artifacts?.artifacts ?? []).slice(0, 4);
}

export function summarizeDeliveryAudit(
  deliveryAudit: SessionDeliveryAuditResponse | null,
): DeliveryAuditRecord[] {
  return (deliveryAudit?.delivery_audit ?? []).slice(0, 4);
}
