/** Node WebSocket adapter. Only this module depends on the ws package. */
import { WebSocketServer } from "ws";
import type { IncomingMessage, Server as HttpServer } from "node:http";
import type { Duplex } from "node:stream";
import { readFileSync, writeFileSync, renameSync, chmodSync } from "node:fs";
import { BridgeBroker, bridgeRunId } from "./bridge.ts";
import { handleApp, type AppEnv } from "./app.ts";
import { forwardedScheme } from "./proxy.ts";

export class NodeBridge {
  broker: BridgeBroker;
  constructor(statePath?: string) {
    let state = {};
    if (statePath)
      try {
        state = JSON.parse(readFileSync(statePath, "utf8"));
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      }
    this.broker = new BridgeBroker(state, async (value) => {
      if (!statePath) return;
      writeFileSync(statePath + ".tmp", JSON.stringify(value), { mode: 0o600 });
      chmodSync(statePath + ".tmp", 0o600);
      renameSync(statePath + ".tmp", statePath);
    });
  }
  sockets = new WebSocketServer({
    noServer: true,
    maxPayload: 65536,
    perMessageDeflate: false,
  });
  async request(request: Request, adminId: string | null): Promise<Response> {
    const path = new URL(request.url).pathname;
    if (path === "/api/bridge/socket" || path === "/api/bridge/ui/socket") {
      if (request.headers.get("Upgrade")?.toLowerCase() !== "websocket")
        return new Response("WebSocket upgrade required", { status: 400 });
      const helper = path === "/api/bridge/socket";
      if (helper ? !(await this.broker.helperAuthorized(request)) : !adminId)
        return new Response("Unauthorized", { status: 401 });
      if (helper && !this.broker.prepareHelper(bridgeRunId(request)))
        return new Response("Bridge already connected", { status: 409 });
      return new Response(null, {
        headers: {
          "X-YOW-Bridge-Role": helper ? "helper" : "ui",
          "X-YOW-Admin": adminId ?? "",
        },
      });
    }
    return this.broker.http(
      request,
      adminId,
      request.headers.get("X-YOW-Peer-IP") ?? "unknown",
    );
  }
  attach(
    server: HttpServer,
    env: AppEnv,
    secure: boolean,
    allowedHosts: Set<string>,
    trustProxy = false,
  ) {
    const health = setInterval(() => this.broker.expireHelpers(), 5000);
    health.unref();
    server.on("close", () => clearInterval(health));
    server.on(
      "upgrade",
      (incoming: IncomingMessage, socket: Duplex, head: Buffer) => {
        void (async () => {
          const authority = incoming.headers.host ?? "";
          if (!allowedHosts.has(authority)) {
            socket.end("HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n");
            return;
          }
          // Same proxy-aware scheme as the HTTP listener: without it a WS
          // upgrade on the public hostname is seen as http, handleApp 308s it,
          // and the handshake is rejected as 403 behind a TLS proxy.
          const url = new URL(
            incoming.url ?? "/",
            `${forwardedScheme(
              secure,
              trustProxy,
              incoming.socket.remoteAddress,
              incoming.headers["x-forwarded-proto"],
            )}://${authority}`,
          );
          if (
            !["/api/bridge/socket", "/api/bridge/ui/socket"].includes(
              url.pathname,
            )
          ) {
            socket.destroy();
            return;
          }
          const headers = new Headers();
          for (const [k, v] of Object.entries(incoming.headers))
            if (v !== undefined)
              headers.set(k, Array.isArray(v) ? v.join(", ") : v);
          const request = new Request(url, { headers });
          const result = await handleApp(request, env);
          const role = result.headers.get("X-YOW-Bridge-Role");
          if (result.status !== 200 || (role !== "helper" && role !== "ui")) {
            socket.end(
              `HTTP/1.1 ${result.status >= 400 ? result.status : 403} Rejected\r\nConnection: close\r\n\r\n`,
            );
            return;
          }
          this.sockets.handleUpgrade(incoming, socket, head, (ws) => {
            const id = crypto.randomUUID();
            try {
              this.broker.attach({
                id,
                role,
                adminId: result.headers.get("X-YOW-Admin") ?? undefined,
                ip: incoming.socket.remoteAddress,
                runId: bridgeRunId(request),
                isOpen: () => ws.readyState === ws.OPEN,
                send: (value) => ws.send(value),
                close: (code, reason) => ws.close(code, reason),
              });
            } catch {
              ws.close(1008, "Bridge already connected");
              return;
            }
            ws.on("message", (data, binary) => {
              if (!binary) this.broker.message(id, data.toString());
            });
            ws.on("close", () => this.broker.detach(id));
            ws.on("error", () => this.broker.detach(id));
          });
        })().catch(() => socket.destroy());
      },
    );
  }
}
