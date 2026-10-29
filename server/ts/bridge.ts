/** Transport-independent single-household Bluetooth bridge broker.
 * Node and Durable Objects own sockets; this class owns pairing and routing.
 * Firmware chunks and Wi-Fi passwords are relayed, never saved in the database.
 */
export const BRIDGE_PROTOCOL = "yow.bridge";
const PAIRING_DOMAIN = "yow-bridge-v1";
export type BridgePeer = {
  id: string;
  role: "helper" | "ui";
  adminId?: string;
  ip?: string;
  runId?: string;
  lastSeen?: number;
  isOpen?(): boolean;
  send(value: string): void;
  close(code: number, reason: string): void;
};
type State = {
  invitation?: { hash: string; expires: number; attempt?: string };
  credentialHash?: string;
  helperId?: string;
  expires?: number;
};
const encoder = new TextEncoder();
export const bridgeHash = async (value: string) =>
  Array.from(
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", encoder.encode(value)),
    ),
    (n) => n.toString(16).padStart(2, "0"),
  ).join("");
const token = () =>
  Array.from(crypto.getRandomValues(new Uint8Array(32)), (n) =>
    n.toString(16).padStart(2, "0"),
  ).join("");
const seconds = () => Math.floor(Date.now() / 1000);
// Application heartbeats distinguish a live process from a half-open socket.
export const BRIDGE_LEASE_MS = 45_000;
export const bridgeRunId = (request: Request) => {
  const id = request.headers.get("X-YOW-Bridge-Run") ?? "";
  return /^[a-zA-Z0-9_-]{1,80}$/.test(id) ? id : undefined;
};
const response = (data: unknown, status = 200) =>
  Response.json(data, { status, headers: { "Cache-Control": "no-store" } });
export const BRIDGE_COMMANDS = new Set([
  "bridge.describe",
  "device.scan.start",
  "device.scan.stop",
  "device.connect",
  "device.disconnect",
  "device.probe",
  "device.complete_setup",
  "device.reveal_secret",
  "device.enroll",
  "device.read_configuration",
  "device.set_server",
  "device.connect_wifi",
  "device.set_time",
  "firmware.generate",
  "firmware.inspect",
  "firmware.install",
  "artifact.begin",
  "artifact.chunk",
  "artifact.finish",
  "artifact.discard",
  "artifact.read",
  "operation.get",
  "operation.cancel",
]);
const privateResults = new Set([
  "device.reveal_secret",
  "device.enroll",
  "artifact.read",
  "artifact.chunk",
]);

export class BridgeBroker {
  state: State;
  peers = new Map<string, BridgePeer>();
  snapshot: Record<string, any> | null = null;
  operations = new Map<
    string,
    { adminId: string; event: Record<string, any> }
  >();
  pending = new Map<
    string,
    { fingerprint: string; adminId: string; clientId: string }
  >();
  private failures = new Map<string, { count: number; until: number }>();
  private persist: (state: State) => Promise<void>;
  constructor(
    state: State = {},
    persist: (state: State) => Promise<void> = async () => {},
  ) {
    this.state = state;
    this.persist = persist;
  }
  helper(): BridgePeer | undefined {
    return [...this.peers.values()].find(
      (p) =>
        p.role === "helper" &&
        (p.isOpen?.() ?? true) &&
        Date.now() - (p.lastSeen ?? 0) < BRIDGE_LEASE_MS,
    );
  }
  expireHelpers() {
    for (const p of this.peers.values()) {
      if (p.role !== "helper") continue;
      if (
        (p.isOpen?.() ?? true) &&
        Date.now() - (p.lastSeen ?? 0) < BRIDGE_LEASE_MS
      )
        continue;
      this.detach(p.id);
      try {
        p.close(4000, "Bridge heartbeat expired");
      } catch {
        /* Already closed. */
      }
    }
  }
  prepareHelper(runId?: string) {
    this.expireHelpers();
    const previous = this.helper();
    if (!previous) return true;
    // An authenticated reconnect by the SAME running process can replace its
    // half-open socket immediately. A second process must wait or be revoked.
    if (!runId || previous.runId !== runId) return false;
    this.detach(previous.id);
    try {
      previous.close(4000, "Replaced by reconnect");
    } catch {
      /* Already closed. */
    }
    return true;
  }
  status() {
    return {
      connected: !!this.helper(),
      helperId: this.state.helperId ?? null,
      ip: this.helper()?.ip ?? null,
      snapshot: this.snapshot,
    };
  }
  send(peer: BridgePeer, value: unknown) {
    try {
      peer.send(JSON.stringify(value));
    } catch {
      this.detach(peer.id);
    }
  }
  broadcast(value: unknown) {
    for (const p of this.peers.values())
      if (p.role === "ui") this.send(p, value);
  }
  attach(peer: BridgePeer) {
    peer.lastSeen ??= Date.now();
    if (
      peer.role === "helper" &&
      this.helper() &&
      this.helper()!.id !== peer.id
    )
      throw new Error("A bridge is already connected");
    this.peers.set(peer.id, peer);
    if (peer.role === "ui")
      this.send(peer, { kind: "ready", clientId: peer.id, ...this.status() });
    else this.broadcast({ kind: "connection", ...this.status() });
  }
  detach(id: string) {
    const peer = this.peers.get(id);
    this.peers.delete(id);
    if (peer?.role === "helper")
      this.broadcast({ kind: "connection", ...this.status() });
  }
  async helperAuthorized(request: Request) {
    const credential =
      request.headers.get("Authorization")?.replace(/^Bearer /, "") ?? "";
    return (
      !!this.state.credentialHash &&
      (this.state.expires ?? 0) > seconds() &&
      /^[a-f0-9]{64}$/.test(credential) &&
      (await bridgeHash(credential)) === this.state.credentialHash
    );
  }
  async invitation(server: string) {
    const value = token();
    this.state.invitation = {
      hash: await bridgeHash(value),
      expires: seconds() + 600,
    };
    await this.persist(this.state);
    return {
      version: 1,
      server,
      token: value,
      expiresAt: new Date(this.state.invitation.expires * 1000).toISOString(),
    };
  }
  async exchange(body: Record<string, unknown>, ip: string) {
    const rate = this.failures.get(ip);
    if (rate && rate.until > seconds() && rate.count >= 10)
      return response({ error: "Too many attempts; try again later" }, 429);
    const invite = this.state.invitation;
    const valid =
      typeof body.token === "string" &&
      /^[a-f0-9]{64}$/.test(body.token) &&
      typeof body.attemptId === "string" &&
      /^[a-zA-Z0-9_-]{1,80}$/.test(body.attemptId) &&
      invite &&
      invite.expires > seconds() &&
      (await bridgeHash(body.token)) === invite.hash &&
      (!invite.attempt || invite.attempt === body.attemptId);
    if (!valid) {
      this.failures.set(ip, {
        count: (rate && rate.until > seconds() ? rate.count : 0) + 1,
        until: seconds() + 600,
      });
      if (this.failures.size > 200)
        this.failures.delete(this.failures.keys().next().value!);
      return response(
        { error: "Invalid, expired, or already used invitation" },
        401,
      );
    }
    if (this.helper() && !invite.attempt)
      return response(
        { error: "Disconnect the current bridge before replacing it" },
        409,
      );
    // Deterministic only for this secret invitation and random attempt ID.
    // Retrying a lost exchange response needs no plaintext credential storage.
    const credential = await bridgeHash(
      `${PAIRING_DOMAIN}:${body.token}:${body.attemptId}`,
    );
    invite.attempt = body.attemptId as string;
    this.state.credentialHash = await bridgeHash(credential);
    this.state.helperId = this.state.helperId ?? crypto.randomUUID();
    this.state.expires = seconds() + 7 * 86400;
    await this.persist(this.state);
    return response({
      credential,
      helperId: this.state.helperId,
      expiresAt: this.state.expires,
    });
  }
  async revoke() {
    const helper = this.helper();
    this.state = {};
    await this.persist(this.state);
    if (helper) {
      helper.close(1008, "Pairing revoked");
      this.detach(helper.id);
    }
    this.snapshot = null;
    this.pending.clear();
    this.operations.clear();
    this.broadcast({ kind: "connection", ...this.status() });
  }
  message(peerId: string, raw: string) {
    const peer = this.peers.get(peerId);
    if (!peer || peer.role !== "helper" || encoder.encode(raw).length > 65536)
      return;
    let event: Record<string, any>;
    try {
      event = JSON.parse(raw);
    } catch {
      peer.close(1003, "Invalid JSON");
      return;
    }
    if (event.protocol !== BRIDGE_PROTOCOL || event.version !== 1) {
      peer.close(1002, "Unsupported protocol");
      return;
    }
    peer.lastSeen = Date.now();
    if (event.kind === "ping") {
      this.send(peer, { protocol: BRIDGE_PROTOCOL, version: 1, kind: "pong" });
      return;
    }
    if (event.kind === "hello" || event.kind === "snapshot") {
      this.snapshot = event.snapshot;
      this.broadcast({ kind: "connection", ...this.status() });
      return;
    }
    if (event.kind === "result" && event.name === "bridge.describe") {
      this.snapshot = event.result;
      this.broadcast({ kind: "connection", ...this.status() });
    }
    if (
      event.name === "firmware.install" &&
      ["accepted", "progress", "result", "error"].includes(event.kind)
    ) {
      const active =
        event.kind === "accepted" || event.kind === "progress"
          ? event.progress
          : {
              operationId: event.operationId,
              name: event.name,
              state: event.kind === "error" ? "failed" : "complete",
              ...(event.kind === "error"
                ? { error: event.error }
                : { result: event.result }),
            };
      if (this.snapshot) this.snapshot.activeOperation = active;
      // OTA progress/outcomes contain no private payload. All signed-in panels
      // can follow the same local operation, including a newly refreshed tab.
      this.broadcast({ kind: "operation", operation: active });
    }
    if (
      !["accepted", "progress", "result", "error", "candidate"].includes(
        event.kind,
      )
    )
      return;
    const route = this.pending.get(event.id);
    const target = this.peers.get(route?.clientId ?? event.replyTo);
    if (target?.role === "ui") this.send(target, event);
    if (route && ["result", "error"].includes(event.kind)) {
      if (!privateResults.has(event.name)) {
        this.operations.set(event.operationId, {
          adminId: route.adminId,
          event,
        });
        while (this.operations.size > 100)
          this.operations.delete(this.operations.keys().next().value!);
      }
      this.pending.delete(event.id);
    }
  }
  async command(adminId: string, body: Record<string, any>) {
    if ((this.state.expires ?? 0) <= seconds()) {
      await this.revoke();
      return response({ error: "Bridge pairing expired" }, 401);
    }
    const helper = this.helper(),
      client = this.peers.get(body.clientId);
    if (!helper)
      return response({ error: "Local Python bridge is disconnected" }, 409);
    if (!client || client.role !== "ui" || client.adminId !== adminId)
      return response({ error: "Reconnect the browser's bridge panel" }, 409);
    if (
      !BRIDGE_COMMANDS.has(body.name) ||
      !body.parameters ||
      typeof body.parameters !== "object" ||
      Array.isArray(body.parameters) ||
      !/^[a-zA-Z0-9_-]{1,80}$/.test(body.id ?? "") ||
      !/^[a-zA-Z0-9_-]{1,80}$/.test(body.operationId ?? "")
    )
      return response({ error: "Invalid bridge command" }, 400);
    if (
      body.name === "firmware.install" &&
      (body.parameters.confirmation !== "FLASH" ||
        !/^[a-f0-9]{64}$/.test(body.parameters.sha256 ?? ""))
    )
      return response(
        { error: "Confirm the selected firmware before flashing" },
        400,
      );
    if (this.pending.size >= 128)
      return response({ error: "Too many pending commands" }, 429);
    const command = {
      protocol: BRIDGE_PROTOCOL,
      version: 1,
      kind: "command",
      id: body.id,
      operationId: body.operationId,
      name: body.name,
      parameters: body.parameters,
      deviceId: body.deviceId,
      connectionGeneration: body.connectionGeneration,
      replyTo: client.id,
    };
    const fingerprint = await bridgeHash(JSON.stringify(command)),
      prior = this.pending.get(body.id);
    if (prior && prior.fingerprint !== fingerprint)
      return response({ error: "Command ID was reused" }, 409);
    this.pending.set(body.id, { fingerprint, adminId, clientId: client.id });
    this.send(helper, command);
    return response(
      { accepted: true, id: body.id, operationId: body.operationId },
      202,
    );
  }
  /** Called only by the authenticated application adapter, except exchange. */
  async http(request: Request, adminId: string | null, ip = "unknown") {
    const url = new URL(request.url),
      path = url.pathname;
    if (path === "/api/bridge/exchange" && request.method === "POST")
      return this.exchange(
        (await request.json()) as Record<string, unknown>,
        ip,
      );
    if (!adminId) return response({ error: "Sign in first" }, 401);
    if (path === "/api/bridge/status" && request.method === "GET")
      return response(this.status());
    if (path === "/api/bridge/invitations" && request.method === "POST") {
      // Consume the forwarded body before answering. Leaving it unread makes
      // workerd report a request-stream error after the response is sent.
      await request.arrayBuffer();
      return response(await this.invitation(url.origin));
    }
    if (path === "/api/bridge/revoke" && request.method === "POST") {
      await request.arrayBuffer();
      await this.revoke();
      return response({ revoked: true });
    }
    if (path === "/api/bridge/commands" && request.method === "POST")
      return this.command(
        adminId,
        (await request.json()) as Record<string, any>,
      );
    const match = /^\/api\/bridge\/operations\/([a-zA-Z0-9_-]+)$/.exec(path);
    if (match && request.method === "GET") {
      const op = this.operations.get(match[1]);
      return op?.adminId === adminId
        ? response(op.event)
        : response(
            { error: "Operation not retained; query the bridge snapshot" },
            404,
          );
    }
    return response({ error: "Not found" }, 404);
  }
}
