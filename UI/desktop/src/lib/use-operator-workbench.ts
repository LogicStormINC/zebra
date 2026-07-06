import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App as AntApp } from "antd";
import { useEffect, useMemo, useState } from "react";
import type { ArtifactSummary, OperatorConfig } from "../types";
import { ZebraApiError, zebraApi } from "./zebra-api";

export function formatOperatorError(error: unknown) {
  if (error instanceof ZebraApiError) {
    if (typeof error.payload === "object" && error.payload && "reason" in error.payload) {
      return String(error.payload.reason);
    }
    return `${error.statusCode} ${error.message}`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Unknown error";
}

export function useOperatorWorkbench(config: OperatorConfig, patchConfig: (patch: Partial<OperatorConfig>) => void) {
  const { message } = AntApp.useApp();
  const queryClient = useQueryClient();
  const api = useMemo(() => zebraApi(config), [config]);
  const [selectedArtifact, setSelectedArtifact] = useState<ArtifactSummary | null>(null);
  const [artifactContentPreview, setArtifactContentPreview] = useState<string | null>(null);
  const [selectedApprovalId, setSelectedApprovalId] = useState<string>("");
  const normalizedSessionId = config.sessionId.trim();

  async function refreshSessionSurface() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["approvals"] }),
      queryClient.invalidateQueries({ queryKey: ["approval-detail"] }),
      queryClient.invalidateQueries({ queryKey: ["session"] }),
      queryClient.invalidateQueries({ queryKey: ["stream"] }),
      queryClient.invalidateQueries({ queryKey: ["memory"] }),
      queryClient.invalidateQueries({ queryKey: ["memory-overview"] }),
      queryClient.invalidateQueries({ queryKey: ["diff"] }),
      queryClient.invalidateQueries({ queryKey: ["artifacts"] }),
      queryClient.invalidateQueries({ queryKey: ["delivery-audit"] }),
      queryClient.invalidateQueries({ queryKey: ["memory-queue-preview"] }),
      queryClient.invalidateQueries({ queryKey: ["memory-queue-review"] }),
    ]);
  }

  const healthQuery = useQuery({
    queryKey: ["health", config.apiBaseUrl],
    queryFn: api.health,
    refetchInterval: 15000,
  });
  const approvalsQuery = useQuery({
    queryKey: ["approvals", config.apiBaseUrl, config.authToken],
    queryFn: api.approvals,
    refetchInterval: 15000,
  });
  const approvals = approvalsQuery.data?.approvals ?? [];

  useEffect(() => {
    if (!approvals.length) {
      setSelectedApprovalId("");
      return;
    }
    if (selectedApprovalId && approvals.some((approval) => approval.approval_id === selectedApprovalId)) {
      return;
    }
    const matchingSessionApproval = normalizedSessionId
      ? approvals.find((approval) => approval.session_id === normalizedSessionId)
      : undefined;
    setSelectedApprovalId(matchingSessionApproval?.approval_id ?? approvals[0]?.approval_id ?? "");
  }, [approvals, normalizedSessionId, selectedApprovalId]);
  const approvalDetailQuery = useQuery({
    queryKey: ["approval-detail", config.apiBaseUrl, config.authToken, selectedApprovalId],
    queryFn: () => api.approval(selectedApprovalId),
    enabled: !!selectedApprovalId,
  });
  const sessionQuery = useQuery({
    queryKey: ["session", config.apiBaseUrl, config.authToken, config.sessionId],
    queryFn: () => api.session(config.sessionId.trim()),
    enabled: !!config.sessionId.trim(),
  });
  const streamQuery = useQuery({
    queryKey: ["stream", config.apiBaseUrl, config.authToken, config.sessionId],
    queryFn: () => api.stream(config.sessionId.trim()),
    enabled: !!config.sessionId.trim(),
  });
  const diffQuery = useQuery({
    queryKey: ["diff", config.apiBaseUrl, config.authToken, config.sessionId],
    queryFn: () => api.diff(config.sessionId.trim()),
    enabled: !!config.sessionId.trim(),
  });
  const memoryQuery = useQuery({
    queryKey: ["memory", config.apiBaseUrl, config.authToken, config.sessionId],
    queryFn: () => api.memory(config.sessionId.trim()),
    enabled: !!config.sessionId.trim(),
  });
  const artifactsQuery = useQuery({
    queryKey: ["artifacts", config.apiBaseUrl, config.authToken, config.sessionId],
    queryFn: () => api.artifacts(config.sessionId.trim()),
    enabled: !!config.sessionId.trim(),
  });
  const deliveryAuditQuery = useQuery({
    queryKey: ["delivery-audit", config.apiBaseUrl, config.authToken, config.sessionId],
    queryFn: () => api.deliveryAudit(config.sessionId.trim()),
    enabled: !!config.sessionId.trim(),
  });
  const overviewQuery = useQuery({
    queryKey: ["memory-overview", config.apiBaseUrl, config.authToken, config.sessionId, config.userId, config.tenantId],
    queryFn: () => api.memoryOverview(config.sessionId.trim()),
    enabled: !!config.sessionId.trim(),
  });

  function onMutationError(error: unknown) {
    message.error(formatOperatorError(error));
  }

  const createSessionMutation = useMutation({
    mutationFn: api.createSession,
    onSuccess(response) {
      patchConfig({ sessionId: response.session_id });
      void refreshSessionSurface();
      message.success(`Session ready: ${response.session_id}`);
    },
    onError: onMutationError,
  });
  const messageAppendMutation = useMutation({
    mutationFn: (content: string) => api.appendMessage(config.sessionId.trim(), { content }),
    onSuccess(response) {
      void refreshSessionSurface();
      message.success(`Message appended at sequence ${response.sequence}`);
    },
    onError: onMutationError,
  });
  const commitMutation = useMutation({
    mutationFn: (payload: { message: string; author_name?: string; author_email?: string }) =>
      api.commit(config.sessionId.trim(), payload),
    onSuccess(response) {
      void refreshSessionSurface();
      if (response.committed) {
        message.success(`Commit created: ${response.commit_sha}`);
        return;
      }
      message.success(response.status ?? "commit handled");
    },
    onError: onMutationError,
  });
  const pullRequestMutation = useMutation({
    mutationFn: (payload: { title: string; body: string; base_branch: string; head_branch?: string; dry_run: boolean }) =>
      api.pullRequest(config.sessionId.trim(), payload),
    onSuccess(response) {
      void refreshSessionSurface();
      const status = response.pull_request?.status ?? response.status ?? "handled";
      message.success(`Pull request flow: ${status}`);
    },
    onError: onMutationError,
  });
  const approveMutation = useMutation({
    mutationFn: (payload: { operator?: string; reason?: string }) => {
      if (!selectedApprovalId) {
        throw new Error("No approval selected");
      }
      return api.approve(selectedApprovalId, payload);
    },
    onSuccess(response) {
      void refreshSessionSurface();
      message.success(`Approval ${response.decision}d`);
    },
    onError: onMutationError,
  });
  const rejectMutation = useMutation({
    mutationFn: (payload: { operator?: string; reason?: string }) => {
      if (!selectedApprovalId) {
        throw new Error("No approval selected");
      }
      return api.reject(selectedApprovalId, payload);
    },
    onSuccess(response) {
      void refreshSessionSurface();
      message.success(`Approval ${response.decision}ed`);
    },
    onError: onMutationError,
  });
  const suspendMutation = useMutation({
    mutationFn: () => api.suspend(config.sessionId.trim()),
    onSuccess(response) {
      void refreshSessionSurface();
      message.success(`Session ${response.status}`);
    },
    onError: onMutationError,
  });
  const cancelMutation = useMutation({
    mutationFn: () => api.cancel(config.sessionId.trim()),
    onSuccess(response) {
      void refreshSessionSurface();
      message.success(`Session ${response.status}`);
    },
    onError: onMutationError,
  });
  const resumeMutation = useMutation({
    mutationFn: () => api.resume(config.sessionId.trim()),
    onSuccess(response) {
      void refreshSessionSurface();
      message.success(`Session ${response.status}`);
    },
    onError: onMutationError,
  });
  const artifactDetailMutation = useMutation({
    mutationFn: (artifactId: string) => api.artifactDetail(config.sessionId.trim(), artifactId),
    onSuccess(response) {
      setSelectedArtifact(response.artifact);
      setArtifactContentPreview(null);
    },
    onError: onMutationError,
  });
  const artifactContentMutation = useMutation({
    mutationFn: async (artifactId: string) => {
      const [detail, content] = await Promise.all([
        api.artifactDetail(config.sessionId.trim(), artifactId),
        api.artifactContent(config.sessionId.trim(), artifactId),
      ]);
      return {
        artifact: detail.artifact,
        text: window.atob(content.content_base64),
      };
    },
    onSuccess(response) {
      setSelectedArtifact(response.artifact);
      setArtifactContentPreview(response.text);
    },
    onError: onMutationError,
  });
  const artifactPruneMutation = useMutation({
    mutationFn: async (artifactId: string) => {
      const response = await api.pruneArtifact(config.sessionId.trim(), artifactId);
      await refreshSessionSurface();
      const detail = await api.artifactDetail(config.sessionId.trim(), artifactId).catch(() => null);
      return {
        response,
        detail,
      };
    },
    onSuccess(result) {
      if (result.detail) {
        setSelectedArtifact(result.detail.artifact);
      }
      setArtifactContentPreview(null);
      message.success(`Artifact ${result.response.status}`);
    },
    onError: onMutationError,
  });
  const confirmMemoryMutation = useMutation({
    mutationFn: (memoryId: string) => api.confirmMemory(config.sessionId.trim(), memoryId),
    onSuccess(response) {
      void refreshSessionSurface();
      message.success(`Memory ${response.decision}: ${response.memory_status}`);
    },
    onError: onMutationError,
  });
  const expireMemoryMutation = useMutation({
    mutationFn: (memoryId: string) => api.expireMemory(config.sessionId.trim(), memoryId),
    onSuccess(response) {
      void refreshSessionSurface();
      message.success(`Memory ${response.decision}: ${response.memory_status}`);
    },
    onError: onMutationError,
  });

  const busy =
    createSessionMutation.isPending ||
    messageAppendMutation.isPending ||
    commitMutation.isPending ||
    pullRequestMutation.isPending ||
    approveMutation.isPending ||
    rejectMutation.isPending ||
    suspendMutation.isPending ||
    cancelMutation.isPending ||
    resumeMutation.isPending ||
    artifactDetailMutation.isPending ||
    artifactContentMutation.isPending ||
    artifactPruneMutation.isPending ||
    confirmMemoryMutation.isPending ||
    expireMemoryMutation.isPending;
  const error =
    messageAppendMutation.error ||
    commitMutation.error ||
    pullRequestMutation.error ||
    approveMutation.error ||
    rejectMutation.error ||
    suspendMutation.error ||
    cancelMutation.error ||
    resumeMutation.error ||
    artifactPruneMutation.error ||
    confirmMemoryMutation.error ||
    expireMemoryMutation.error;

  return {
    api,
    selectedArtifact,
    artifactContentPreview,
    busy,
    errorText: error ? formatOperatorError(error) : null,
    queries: {
      healthQuery,
      approvalsQuery,
      approvalDetailQuery,
      sessionQuery,
      streamQuery,
      diffQuery,
      memoryQuery,
      artifactsQuery,
      deliveryAuditQuery,
      overviewQuery,
    },
    actions: {
      selectApproval: (approvalId: string, sessionId: string) => {
        setSelectedApprovalId(approvalId);
        patchConfig({ sessionId });
      },
      refreshSessionSurface,
      createSession: (payload: { title: string; prompt: string; execute: boolean }) =>
        createSessionMutation.mutateAsync(payload),
      appendMessage: (content: string) => messageAppendMutation.mutateAsync(content),
      commit: (payload: { message: string; author_name?: string; author_email?: string }) =>
        commitMutation.mutateAsync(payload),
      pullRequest: (payload: { title: string; body: string; base_branch: string; head_branch?: string; dry_run: boolean }) =>
        pullRequestMutation.mutateAsync(payload),
      approve: (payload: { operator?: string; reason?: string }) => approveMutation.mutateAsync(payload),
      reject: (payload: { operator?: string; reason?: string }) => rejectMutation.mutateAsync(payload),
      suspend: () => suspendMutation.mutateAsync(),
      cancel: () => cancelMutation.mutateAsync(),
      resume: () => resumeMutation.mutateAsync(),
      inspectArtifact: (artifactId: string) => artifactDetailMutation.mutateAsync(artifactId),
      readArtifact: (artifactId: string) => artifactContentMutation.mutateAsync(artifactId),
      pruneArtifact: (artifactId: string) => artifactPruneMutation.mutateAsync(artifactId),
      confirmMemory: (memoryId: string) => confirmMemoryMutation.mutateAsync(memoryId),
      expireMemory: (memoryId: string) => expireMemoryMutation.mutateAsync(memoryId),
      closeArtifactModal: () => {
        setSelectedArtifact(null);
        setArtifactContentPreview(null);
      },
    },
  };
}
