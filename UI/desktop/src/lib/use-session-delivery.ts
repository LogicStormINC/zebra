import { useMutation } from "@tanstack/react-query";
import { useEffect } from "react";
import { toErrorMessage } from "./chat-surface";
import type { PullRequestInput, SessionDeliveryController } from "./session-delivery";
import { buildPullRequestPayload } from "./session-delivery";
import type { ZebraApiClient } from "./zebra-api";

export function useSessionDelivery(
  api: ZebraApiClient,
  sessionId: string | undefined,
  onChanged: () => Promise<unknown>,
): SessionDeliveryController {
  const requireSession = () => {
    if (!sessionId) throw new Error("No active session");
    return sessionId;
  };
  const commit = useMutation({
    mutationFn: (input: { message: string }) => api.commit(requireSession(), input),
    onSuccess: onChanged,
  });
  const pullRequest = useMutation({
    mutationFn: ({ input, execute }: { input: PullRequestInput; execute: boolean }) =>
      api.pullRequest(requireSession(), buildPullRequestPayload(input, execute)),
    onSuccess: onChanged,
  });
  useEffect(() => {
    commit.reset();
    pullRequest.reset();
  }, [sessionId]);
  return {
    busy: commit.isPending || pullRequest.isPending,
    commitResult: commit.data,
    errorText: commit.error || pullRequest.error ? toErrorMessage(commit.error ?? pullRequest.error) : null,
    pullRequestResult: pullRequest.data,
    commit: commit.mutateAsync,
    planPullRequest: (input) => pullRequest.mutateAsync({ input, execute: false }),
    executePullRequest: (input) => pullRequest.mutateAsync({ input, execute: true }),
  };
}
