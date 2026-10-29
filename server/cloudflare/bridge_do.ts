/** One Durable Object per installation, with hibernating outbound bridge/UI sockets. */
import {
  BridgeBroker,
  BRIDGE_LEASE_MS,
  bridgeRunId,
  type BridgePeer,
} from "../ts/bridge.ts";
import { BRIDGE_PROTOCOL } from "../ts/bridge.ts";

type Attachment = {
  id: string;
  role: "helper" | "ui";
  adminId?: string;
  ip?: string;
  runId?: string;
  lastSeen?: number;
};
export class BridgeDurableObject {
  broker!: BridgeBroker;
  ready: Promise<void>;
  private ctx: DurableObjectState;
  constructor(ctx: DurableObjectState) {
    this.ctx = ctx;
    this.ready = ctx.blockConcurrencyWhile(async () => {
      this.broker = new BridgeBroker(
        (await ctx.storage.get("pairing")) ?? {},
        async (state) => {
          await ctx.storage.put("pairing", state);
        },
      );
      for (const socket of ctx.getWebSockets()) {
        const a = socket.deserializeAttachment() as Attachment;
        // getWebSockets() can also return CLOSING sockets after hibernation.
        if (a && socket.readyState === WebSocket.OPEN) {
          a.lastSeen ??= Date.now();
          socket.serializeAttachment(a);
          this.broker.peers.set(a.id, this.peer(socket, a));
        }
      }
      this.broker.expireHelpers();
      if (this.broker.helper() && !(await ctx.storage.getAlarm()))
        await ctx.storage.setAlarm(Date.now() + BRIDGE_LEASE_MS);
    });
  }
  peer(socket: WebSocket, a: Attachment): BridgePeer {
    return {
      ...a,
      isOpen: () => socket.readyState === WebSocket.OPEN,
      send: (value) => socket.send(value),
      close: (code, reason) => socket.close(code, reason),
    };
  }
  async fetch(request: Request): Promise<Response> {
    await this.ready;
    this.broker.expireHelpers();
    // This header is supplied only by the Worker after cookie/CSRF validation.
    // The Durable Object is not an independently public HTTP endpoint.
    const adminId = request.headers.get("X-YOW-Authenticated-Admin");
    const path = new URL(request.url).pathname;
    if (path === "/api/bridge/socket" || path === "/api/bridge/ui/socket") {
      if (request.headers.get("Upgrade")?.toLowerCase() !== "websocket")
        return new Response("Upgrade required", { status: 400 });
      const role = path === "/api/bridge/socket" ? "helper" : "ui";
      if (
        role === "helper"
          ? !(await this.broker.helperAuthorized(request))
          : !adminId
      )
        return new Response("Unauthorized", { status: 401 });
      const runId = bridgeRunId(request);
      if (role === "helper" && !this.broker.prepareHelper(runId))
        return new Response("Bridge already connected", { status: 409 });
      const pair = new WebSocketPair(),
        [client, server] = Object.values(pair);
      const a: Attachment = {
        id: crypto.randomUUID(),
        role,
        adminId: adminId ?? undefined,
        ip: request.headers.get("CF-Connecting-IP") ?? "unknown",
        runId,
        lastSeen: Date.now(),
      };
      server.serializeAttachment(a);
      this.ctx.acceptWebSocket(server);
      this.broker.attach(this.peer(server, a));
      if (role === "helper")
        await this.ctx.storage.setAlarm(Date.now() + BRIDGE_LEASE_MS);
      // A hibernated instance has no volatile snapshot. Ask the existing helper
      // for one; the returned describe result updates the shared status.
      if (role === "ui" && !this.broker.snapshot && this.broker.helper()) {
        this.broker.send(this.broker.helper()!, {
          protocol: BRIDGE_PROTOCOL,
          version: 1,
          kind: "command",
          name: "bridge.describe",
          parameters: {},
          id: crypto.randomUUID(),
          operationId: crypto.randomUUID(),
          replyTo: a.id,
        });
      }
      return new Response(null, { status: 101, webSocket: client });
    }
    return this.broker.http(
      request,
      adminId,
      request.headers.get("CF-Connecting-IP") ?? "unknown",
    );
  }
  async webSocketMessage(socket: WebSocket, message: string | ArrayBuffer) {
    await this.ready;
    if (typeof message === "string") {
      const a = socket.deserializeAttachment() as Attachment;
      this.broker.message(a.id, message);
      const peer = this.broker.peers.get(a.id);
      if (peer) socket.serializeAttachment({ ...a, lastSeen: peer.lastSeen });
    }
  }
  async alarm() {
    await this.ready;
    this.broker.expireHelpers();
    const helper = this.broker.helper();
    if (helper)
      await this.ctx.storage.setAlarm(
        (helper.lastSeen ?? Date.now()) + BRIDGE_LEASE_MS,
      );
  }
  async webSocketClose(socket: WebSocket, code: number, reason: string) {
    await this.ready;
    this.broker.detach((socket.deserializeAttachment() as Attachment).id);
    try {
      socket.close(code, reason);
    } catch {
      /* Already closed. */
    }
  }
  async webSocketError(socket: WebSocket) {
    await this.webSocketClose(socket, 1011, "Connection error");
  }
}
