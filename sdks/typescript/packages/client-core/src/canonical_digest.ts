/** Stable browser-native SHA-256 digest without a Node.js runtime dependency. */
export async function canonicalDigest(payload: unknown): Promise<string> {
  const json = JSON.stringify(payload, (_key, value) =>
    value !== null && typeof value === "object" && !Array.isArray(value)
      ? Object.keys(value as Record<string, unknown>)
          .sort()
          .reduce<Record<string, unknown>>((acc, key) => {
            acc[key] = (value as Record<string, unknown>)[key];
            return acc;
          }, {})
      : value,
  );
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(json));
  return [...new Uint8Array(digest)]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}
