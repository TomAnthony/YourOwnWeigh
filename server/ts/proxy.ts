/** Scheme to treat an incoming request as. A trusted reverse proxy terminates
 * TLS and forwards over plain HTTP, so honour its X-Forwarded-Proto. The value
 * is clamped to "http"/"https" so a malformed header (e.g. "/") can never reach
 * new URL() and crash the listener; unknown values default to https, since a
 * trusted proxy is terminating TLS in front of us. */
export function forwardedScheme(
  secure: boolean,
  trustProxy: boolean,
  forwardedProto: string | string[] | undefined,
): "http" | "https" {
  if (secure) return "https";
  if (!trustProxy) return "http";
  const value = (
    Array.isArray(forwardedProto)
      ? (forwardedProto[0] ?? "")
      : (forwardedProto ?? "")
  )
    .split(",")[0]
    .trim()
    .toLowerCase();
  return value === "http" ? "http" : "https";
}
