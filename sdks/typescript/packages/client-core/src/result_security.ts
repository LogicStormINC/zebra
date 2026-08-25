/** Receipt results must never carry token/cookie/secret fields. */
export function scrubResult(
  result: Record<string, unknown>,
): Record<string, unknown> {
  return scrubRecord(result, new WeakSet<object>(), 0);
}

function scrubRecord(
  result: Record<string, unknown>,
  seen: WeakSet<object>,
  depth: number,
): Record<string, unknown> {
  if (depth > 16 || seen.has(result)) return { error: "invalid_nested_result" };
  seen.add(result);
  const forbidden = ["token", "cookie", "secret", "password", "authorization"];
  const scrubbed: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(result)) {
    if (forbidden.some((token) => key.toLowerCase().includes(token))) {
      scrubbed[key] = "__redacted__";
    } else {
      scrubbed[key] = scrubValue(value, seen, depth + 1);
    }
  }
  seen.delete(result);
  return scrubbed;
}

function scrubValue(value: unknown, seen: WeakSet<object>, depth: number): unknown {
  if (depth > 16) return "__truncated__";
  if (Array.isArray(value)) {
    if (seen.has(value)) return "__circular__";
    seen.add(value);
    const scrubbed = value.map((item) => scrubValue(item, seen, depth + 1));
    seen.delete(value);
    return scrubbed;
  }
  if (value !== null && typeof value === "object") {
    return scrubRecord(value as Record<string, unknown>, seen, depth);
  }
  return value;
}
