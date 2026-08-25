import type { ReceiptSubmission } from "../../contracts/src/index.ts";
import { scrubResult } from "./result_security.ts";

export function normalizeReceipt(receipt: ReceiptSubmission): ReceiptSubmission {
  let result = scrubResult(receipt.result);
  let status = receipt.status;
  if (new TextEncoder().encode(JSON.stringify(result)).byteLength > 16_384) {
    result = { error: "receipt_result_too_large" };
    status = "failed";
  }
  return { ...receipt, result, status };
}

export async function submitClientReceipt(
  deps: {
    fetchImpl: typeof fetch;
    baseUrl: string;
    sessionCredential: string;
    controllerFenceToken?: string | undefined;
  },
  submission: ReceiptSubmission,
  stopped: () => boolean,
): Promise<"accepted" | "rejected" | "retry"> {
  const receipt = normalizeReceipt(submission);
  const body = JSON.stringify({
    receipt_id: crypto.randomUUID(),
    effect_id: receipt.effect_id,
    idempotency_key: `sdk-receipt:${receipt.effect_id}`,
    request_digest: receipt.request_digest,
    status: receipt.status,
    result: receipt.result,
    controller: true,
    received_at: new Date().toISOString(),
  });
  for (let attempt = 0; attempt < 5; attempt += 1) {
    if (stopped()) return "retry";
    try {
      const response = await deps.fetchImpl(
        `${deps.baseUrl}/v1/client-effects/${receipt.effect_id}/receipts`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Zebra-Client-Session": deps.sessionCredential,
            "Idempotency-Key": `sdk-receipt:${receipt.effect_id}`,
            "X-Zebra-Client-Fence": deps.controllerFenceToken ?? "",
          },
          body,
        },
      );
      if (response.ok) return "accepted";
      if (
        response.status < 500 &&
        response.status !== 408 &&
        response.status !== 429
      ) return "rejected";
    } catch {
      // Network failure retries with bounded backoff.
    }
    await new Promise((resolve) => setTimeout(resolve, 250 * (attempt + 1)));
  }
  return "retry";
}
