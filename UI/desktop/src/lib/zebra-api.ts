import type { OperatorConfig } from "../types";
export { ZebraApiError } from "./zebra-api-helpers";
import { buildCoreApiClient } from "./zebra-api-core";
import { buildMemoryApi } from "./zebra-api-memory";
import { buildQueueApiClient } from "./zebra-api-queue";

export function zebraApi(config: OperatorConfig) {
  const baseUrl = config.apiBaseUrl;
  const authToken = config.authToken.trim();

  return {
    ...buildCoreApiClient({ baseUrl, authToken }),
    ...buildMemoryApi(baseUrl, authToken, config.userId, config.tenantId),
    ...buildQueueApiClient(baseUrl, authToken),
  };
}

export type ZebraApiClient = ReturnType<typeof zebraApi>;
