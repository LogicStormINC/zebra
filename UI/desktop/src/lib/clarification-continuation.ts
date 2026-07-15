export function buildClarificationResponsePayload(
  clarificationId: string,
  content: string,
) {
  const normalizedId = clarificationId.trim();
  const normalizedContent = content.trim();
  if (!normalizedId || !normalizedContent) {
    throw new Error("Clarification id and response are required");
  }
  return {
    content: normalizedContent,
    clarification_id: normalizedId,
  };
}
