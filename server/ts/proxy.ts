import { isIP } from "node:net";

/** A loopback or private/link-local address: the local reverse proxy, or the
 * Docker bridge gateway it reaches Node through. A public peer is never one of
 * these, so forwarded headers from a direct internet client are not trusted. */
export function isTrustedProxyPeer(ip: string | undefined): boolean {
  if (!ip) return false;
  const v4 = ip.startsWith("::ffff:") ? ip.slice(7) : ip;
  if (isIP(v4) === 4) {
    const o = v4.split(".").map(Number);
    if (
      o.length !== 4 ||
      o.some((n) => !Number.isInteger(n) || n < 0 || n > 255)
    )
      return false;
    return (
      o[0] === 127 || // loopback
      o[0] === 10 || // 10.0.0.0/8
      (o[0] === 172 && o[1] >= 16 && o[1] <= 31) || // 172.16.0.0/12 (Docker)
      (o[0] === 192 && o[1] === 168) || // 192.168.0.0/16
      (o[0] === 169 && o[1] === 254) // 169.254.0.0/16 link-local
    );
  }
  const l = ip.toLowerCase();
  return (
    l === "::1" || // loopback
    /^f[cd]/.test(l) || // fc00::/7 unique-local
    /^fe[89ab]/.test(l) // fe80::/10 link-local
  );
}

/** Scheme to treat an incoming request as. A trusted reverse proxy terminates
 * TLS and forwards over plain HTTP, so honour its X-Forwarded-Proto — but only
 * when YOW_TRUST_PROXY is set AND the socket peer is itself loopback/private, so
 * a direct public client cannot send `X-Forwarded-Proto: https` to bypass the
 * HTTPS requirement over plaintext. The value is clamped to http/https so a
 * malformed header can never crash new URL(); unknown values default to https
 * (a trusted proxy is terminating TLS in front of us). */
export function forwardedScheme(
  secure: boolean,
  trustProxy: boolean,
  peer: string | undefined,
  forwardedProto: string | string[] | undefined,
): "http" | "https" {
  if (secure) return "https";
  if (!trustProxy || !isTrustedProxyPeer(peer)) return "http";
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
