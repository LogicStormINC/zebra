export interface ArtifactAccess {
  class: string;
  required_policy_profile: string;
  session_policy_profile: string;
  allowed: boolean;
}

export interface ArtifactRetrieval {
  status: string;
  retrievable: boolean;
  uri: string | null;
}

export interface ArtifactLifecycle {
  status: string;
  retained_until: string | null;
  pruned_at: string | null;
  expired: boolean;
}

export interface ArtifactSummary {
  artifact_id: string;
  sequence: number;
  source: string;
  kind: string;
  label: string;
  uri: string | null;
  preview: string | null;
  preview_state: {
    redacted: boolean;
    truncated: boolean;
  };
  metadata: Record<string, unknown>;
  retrieval: ArtifactRetrieval;
  lifecycle: ArtifactLifecycle | null;
  access: ArtifactAccess;
}

export interface SessionArtifactsResponse {
  session_id: string;
  artifacts: ArtifactSummary[];
}

export interface SessionArtifactDetailResponse {
  session_id: string;
  status: string;
  artifact: ArtifactSummary;
}

export interface SessionArtifactContentResponse {
  session_id: string;
  artifact_id: string;
  status: string;
  access: ArtifactAccess;
  encoding: string;
  content_base64: string;
  size_bytes: number;
}

export interface SessionArtifactPruneResponse {
  session_id: string;
  artifact_id: string;
  status: string;
  access_class?: string;
  required_policy_profile?: string;
  lifecycle: ArtifactLifecycle | null;
}

export interface DeliveryAuditRecord {
  action: string;
  status: string;
  status_code: number;
  policy_profile: string;
  idempotency_key: string | null;
  result_metadata: Record<string, unknown>;
  created_at: string;
}

export interface SessionDeliveryAuditResponse {
  session_id: string;
  delivery_audit: DeliveryAuditRecord[];
}
