/** Local Node application: loopback HTTP first run, optional native HTTPS.
 * Scale-facing fixed ports are forwarded by the documented reverse proxy.
 * Never run Node as root. All persistent development/deployment data is local/.
 */
import { createServer as createHttpsServer } from "node:https";
import {
  createServer as createHttpServer,
  type IncomingMessage,
  type ServerResponse,
} from "node:http";
import { readFileSync, existsSync, mkdirSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import { randomBytes } from "node:crypto";
import { isIP } from "node:net";
import { LocalSqlite } from "./sqlite.ts";
import { handleApp, type AppEnv } from "./app.ts";
import { captureWithings, firmwareOffer } from "./withings_capture.ts";
import { NodeBridge } from "./bridge_node.ts";
import { forwardedScheme } from "./proxy.ts";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const SCALE_PATHS = new Set([
  "/once",
  "/session",
  "/measure",
  "/v2/screen",
  "/v2/summary",
  "/v2/weather",
  "/v2/event",
  "/v2/measure",
  "/v2/feature",
]);
const mime: Record<string, string> = {
  "app.css": "text/css; charset=utf-8",
  "app.js": "text/javascript; charset=utf-8",
  "firmware.js": "text/javascript; charset=utf-8",
  "favicon.png": "image/png",
  "YourOwnWeigh-Sync.shortcut": "application/octet-stream",
};
export function assets(): AppEnv["ASSETS"] {
  return {
    async fetch(request) {
      const filename = decodeURIComponent(
        new URL(request.url).pathname.slice(1),
      );
      if (!(filename in mime))
        return new Response("Not Found", { status: 404 });
      const path = filename.endsWith(".shortcut")
        ? join(ROOT, "connectors/Apple Health/YourOwnWeigh Sync.shortcut")
        : join(ROOT, "server/static", filename);
      try {
        return new Response(readFileSync(path), {
          headers: {
            "Content-Type": mime[filename],
            "Cache-Control": filename.endsWith(".shortcut")
              ? "public, max-age=3600"
              : "no-cache",
            "X-Content-Type-Options": "nosniff",
            ...(filename.endsWith(".shortcut")
              ? {
                  "Content-Disposition":
                    'attachment; filename="YourOwnWeigh Sync.shortcut"',
                }
              : {}),
          },
        });
      } catch {
        return new Response("Not Found", { status: 404 });
      }
    },
  };
}
/** A loopback or private/link-local address: either the local reverse proxy or
 * the Docker bridge gateway it reaches Node through. A public peer is never one
 * of these, so a request arriving directly from the internet cannot spoof
 * X-Forwarded-For to poison the login limits. */
function isTrustedProxyPeer(ip: string): boolean {
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
/** Client address used for failed-password limits. With YOW_TRUST_PROXY=1 the
 * container is reachable only through the operator's reverse proxy (its port is
 * published to loopback), and that proxy may reach Node from a Docker bridge
 * address rather than loopback. Trust the last hop of its X-Forwarded-For, but
 * only when the immediate peer is itself loopback/private — never from a public
 * address — so one stranger cannot lock everyone out and a direct internet
 * client cannot spoof the header. */
export function peerAddress(
  remote: string | undefined,
  forwarded: string | string[] | undefined,
  trustProxy: boolean,
): string {
  const peer = remote ?? "unknown";
  if (!trustProxy || forwarded === undefined || !isTrustedProxyPeer(peer))
    return peer;
  const last = (Array.isArray(forwarded) ? forwarded.join(",") : forwarded)
    .split(",")
    .pop()!
    .trim();
  return isIP(last) ? last : peer;
}
export function localListener(
  env: AppEnv,
  secure: boolean,
  allowedHosts: Set<string>,
  scaleOnly = false,
  trustProxy = false,
) {
  return async (
    incoming: IncomingMessage,
    outgoing: ServerResponse,
  ): Promise<void> => {
    const authority = incoming.headers.host ?? "";
    if (!allowedHosts.has(authority)) {
      outgoing.writeHead(403);
      outgoing.end("Unrecognized Host header");
      return;
    }
    // Behind a trusted reverse proxy the request arrives over plain HTTP; treat
    // it by the forwarded scheme so there is no redirect loop and session
    // cookies stay Secure. forwardedScheme clamps the header to http/https so a
    // malformed value cannot crash new URL().
    const url = new URL(
      incoming.url ?? "/",
      `${forwardedScheme(secure, trustProxy, incoming.headers["x-forwarded-proto"])}://${authority}`,
    );
    if (
      scaleOnly &&
      !(incoming.method === "POST" && SCALE_PATHS.has(url.pathname))
    ) {
      outgoing.writeHead(404);
      outgoing.end("Not Found");
      return;
    }
    try {
      let size = 0;
      const chunks: Buffer[] = [];
      const limit =
        url.pathname === "/api/backup/import" ? 10 * 1024 * 1024 : 256000;
      for await (const chunk of incoming) {
        size += chunk.length;
        if (size > limit) {
          outgoing.writeHead(413);
          outgoing.end("Request too large");
          return;
        }
        chunks.push(chunk);
      }
      const headers = new Headers();
      for (const [name, value] of Object.entries(incoming.headers))
        if (value !== undefined && name !== "host")
          headers.set(name, Array.isArray(value) ? value.join(", ") : value);
      headers.set(
        "X-YOW-Peer-IP",
        peerAddress(
          incoming.socket.remoteAddress,
          incoming.headers["x-forwarded-for"],
          trustProxy,
        ),
      );
      const request = new Request(url, {
        method: incoming.method,
        headers,
        body: ["GET", "HEAD"].includes(incoming.method ?? "")
          ? undefined
          : Buffer.concat(chunks),
      });
      const response = await handleApp(request, env);
      const responseHeaders = new Headers(response.headers);
      if (secure)
        responseHeaders.set("Strict-Transport-Security", "max-age=31536000");
      outgoing.writeHead(response.status, Object.fromEntries(responseHeaders));
      outgoing.end(Buffer.from(await response.arrayBuffer()));
    } catch (error) {
      console.error(
        "Request failed:",
        error instanceof Error ? error.name : "Unknown error",
      );
      if (!outgoing.headersSent)
        outgoing.writeHead(500, {
          "Content-Type": "text/plain",
          "Cache-Control": "no-store",
        });
      outgoing.end("Internal Server Error");
    }
  };
}
export async function startLocal() {
  const config = process.env;
  const dbPath = config.YOW_DB_PATH || join(ROOT, "local/data/yow.sqlite3");
  const store = new LocalSqlite(dbPath);
  const tokenPath = join(dirname(dbPath), "bootstrap-token.txt");
  let bootstrap = config.YOW_BOOTSTRAP_TOKEN;
  const initialized = await store
    .prepare("SELECT value FROM settings WHERE key='admin_password'")
    .first();
  if (!bootstrap && !initialized) {
    if (existsSync(tokenPath))
      bootstrap = readFileSync(tokenPath, "utf8").trim();
    else {
      bootstrap = randomBytes(32).toString("hex");
      mkdirSync(dirname(tokenPath), { recursive: true, mode: 0o700 });
      writeFileSync(tokenPath, bootstrap + "\n", { mode: 0o600, flag: "wx" });
    }
  }
  if (bootstrap && bootstrap.length < 24)
    throw new Error("Bootstrap token must be at least 24 characters");
  const host = config.YOW_LISTEN_HOST || "127.0.0.1",
    port = Number(config.YOW_PORT || "8080");
  const cert = config.YOW_TLS_CERT,
    key = config.YOW_TLS_KEY;
  const secure = !!(cert && key);
  const trustProxy = config.YOW_TRUST_PROXY === "1";
  // Plain HTTP must stay on loopback unless the operator declares a reverse
  // proxy in front (YOW_TRUST_PROXY=1) that terminates TLS and forwards to this
  // listener. That lets the Docker image bind 0.0.0.0 inside its own network
  // namespace while real TLS is handled by the proxy.
  if (
    !secure &&
    !trustProxy &&
    !["127.0.0.1", "::1", "localhost"].includes(host)
  )
    throw new Error(
      "Plain HTTP dashboard must bind to loopback unless YOW_TRUST_PROXY=1 (a reverse proxy terminates TLS in front of it).",
    );
  if (!Number.isInteger(port) || port < 1 || port > 65535)
    throw new Error("Invalid YOW_PORT");
  const publicOrigin =
    config.YOW_PUBLIC_ORIGIN ??
    `${secure ? "https" : "http"}://${host === "::1" ? "[::1]" : host}:${port}`;
  const origin = new URL(publicOrigin);
  const allowedHosts = new Set([
    origin.host,
    `${host}:${port}`,
    `localhost:${port}`,
    `127.0.0.1:${port}`,
    `[::1]:${port}`,
  ]);
  const bridge = new NodeBridge(join(dirname(dbPath), "bridge-pairing.json"));
  const env: AppEnv = {
    DB: store.asD1(),
    ALLOW_HTTP_SCALE: true,
    YOW_BOOTSTRAP_TOKEN: bootstrap,
    ASSETS: assets(),
    captureWithings,
    lookupFirmwareOffer: firmwareOffer,
    bridgeRequest: (request, adminId) => bridge.request(request, adminId),
  };
  const listener = localListener(env, secure, allowedHosts, false, trustProxy);
  const server = secure
    ? createHttpsServer(
        { cert: readFileSync(cert!), key: readFileSync(key!) },
        listener,
      )
    : createHttpServer(listener);
  bridge.attach(server, env, secure, allowedHosts, trustProxy);
  server.listen(port, host, () => {
    console.log(`YourOwnWeigh: ${origin.origin}`);
    if (!initialized) console.log(`First-run bootstrap token: ${bootstrap}`);
  });
  // Optional separate scale-only listener behind a fixed-port proxy. It never
  // serves the dashboard, Sync API, bootstrap, or bridge WebSocket routes.
  const scalePort = config.YOW_SCALE_PORT
    ? Number(config.YOW_SCALE_PORT)
    : null;
  let scaleServer: ReturnType<typeof createHttpServer> | undefined;
  if (scalePort) {
    if (!Number.isInteger(scalePort) || scalePort < 1 || scalePort > 65535)
      throw new Error("Invalid scale listener port");
    const scaleHost = config.YOW_SCALE_HOST || "127.0.0.1";
    const proxyHost = config.YOW_SCALE_PROXY_HOST || `127.0.0.1:${scalePort}`;
    scaleServer = createHttpServer(
      localListener(env, false, new Set([proxyHost]), true, trustProxy),
    );
    scaleServer.listen(scalePort, scaleHost, () =>
      console.log(`Scale-only HTTP listener: ${scaleHost}:${scalePort}`),
    );
  }
  const close = () => {
    server.close();
    scaleServer?.close();
    bridge.sockets.close();
    store.close();
  };
  for (const signal of ["SIGINT", "SIGTERM"] as const)
    process.once(signal, () => {
      close();
      process.exit(0);
    });
  return { server, store, bridge, close };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href)
  void startLocal().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
