/**
 * Client-safe API helpers. Deliberately free of server-only imports
 * (`next/headers`) so the billing cart can use them inside client components.
 */

/** Envelope every API error uses: { error, code, details }. */
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Field-level validation failures from the API, if any. */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError)) return {};
  const fields = error.details?.fields;
  if (!Array.isArray(fields)) return {};
  return Object.fromEntries(
    fields
      .filter((f): f is { field: string; message: string } =>
        Boolean(f && typeof f === "object" && "field" in f && "message" in f),
      )
      .map((f) => [f.field, f.message]),
  );
}

/**
 * A stable Idempotency-Key for one billing attempt. Generated once per
 * checkout attempt so a retry after a network blip replays rather than
 * double-charging.
 */
export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `bill-${crypto.randomUUID()}`;
  }
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `bill-${hex}`;
}
