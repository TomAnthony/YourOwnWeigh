import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { BridgeBroker, BRIDGE_COMMANDS, BRIDGE_LEASE_MS } from "../bridge.ts";
const origin = "https://example.test";
test("broker command names match the published Python/web contract", () => {
  const commands = JSON.parse(
    readFileSync(
      new URL("../../../contracts/bridge/v1/commands.json", import.meta.url),
      "utf8",
    ),
  );
  assert.deepEqual([...BRIDGE_COMMANDS].sort(), Object.keys(commands).sort());
});

test("same-process reconnect replaces a half-open socket, another process waits", () => {
  const broker = new BridgeBroker();
  const closed: any[] = [];
  broker.attach({
    id: "old",
    role: "helper",
    runId: "process-one",
    send: () => {},
    close: (...args) => closed.push(args),
  });
  assert.equal(broker.prepareHelper("process-two"), false);
  assert.equal(broker.prepareHelper(), false);
  assert.equal(broker.prepareHelper("process-one"), true);
  assert.equal(closed.length, 1);
  broker.attach({
    id: "new",
    role: "helper",
    runId: "process-one",
    send: () => {},
    close: () => {},
  });
  broker.detach("old"); // Late close callback must not detach the replacement.
  assert.equal(broker.helper()?.id, "new");
});

test("heartbeat lease and socket readiness bound stale connected status", () => {
  const broker = new BridgeBroker();
  const events: any[] = [];
  broker.attach({
    id: "ui",
    role: "ui",
    send: (v) => events.push(JSON.parse(v)),
    close: () => {},
  });
  broker.attach({
    id: "helper",
    role: "helper",
    send: (v) => events.push(JSON.parse(v)),
    close: () => {},
  });
  const peer = broker.helper()!;
  peer.lastSeen = Date.now() - BRIDGE_LEASE_MS - 1;
  assert.equal(broker.status().connected, false);
  broker.message(
    "helper",
    JSON.stringify({ protocol: "yow.bridge", version: 1, kind: "ping" }),
  );
  assert.equal(events.at(-1).kind, "pong");
  assert.equal(broker.status().connected, true);
  peer.isOpen = () => false;
  broker.expireHelpers();
  assert.equal(events.at(-1).connected, false);
  assert.equal(broker.peers.has("helper"), false);
  assert.equal(broker.prepareHelper("another-process"), true);
});

test("OTA progress survives UI refresh and hibernation without replaying START", () => {
  const broker = new BridgeBroker();
  const events: any[] = [];
  broker.attach({
    id: "helper",
    role: "helper",
    send: () => {},
    close: () => {},
  });
  const emit = (event: any) =>
    broker.message(
      "helper",
      JSON.stringify({ protocol: "yow.bridge", version: 1, ...event }),
    );
  emit({ kind: "hello", snapshot: { device: null } });
  const progress = {
    operationId: "ota",
    name: "firmware.install",
    state: "running",
    stage: "transferring",
    bytesDone: 500,
    bytesTotal: 1000,
  };
  // pending routing is absent, as after DO hibernation. Public operation data
  // still goes to a new browser; private results retain their original route.
  emit({
    kind: "progress",
    name: "firmware.install",
    operationId: "ota",
    progress,
  });
  broker.attach({
    id: "refreshed",
    role: "ui",
    send: (v) => events.push(JSON.parse(v)),
    close: () => {},
  });
  assert.deepEqual(events.at(-1).snapshot.activeOperation, progress);
  emit({
    kind: "result",
    name: "firmware.install",
    operationId: "ota",
    result: { transferred: true, runningFirmwareConfirmed: false },
  });
  assert.equal(events.at(-1).kind, "operation");
  assert.equal(events.at(-1).operation.state, "complete");
});
test("bridge invitation, private result routing, duplicate guard, and revocation", async () => {
  let saved: any;
  const broker = new BridgeBroker({}, async (s) => {
    saved = structuredClone(s);
  });
  const invitation = await broker.invitation(origin);
  assert.equal(saved.invitation.hash.length, 64);
  assert.notEqual(saved.invitation.hash, invitation.token);
  const exchange = async (attemptId: string) =>
    broker.exchange({ token: invitation.token, attemptId }, "test-ip");
  const first = (await (await exchange("attempt1")).json()) as any;
  assert.deepEqual(await (await exchange("attempt1")).json(), first);
  assert.equal((await exchange("attempt2")).status, 401);
  assert.equal(
    await broker.helperAuthorized(
      new Request(origin, {
        headers: { Authorization: `Bearer ${first.credential}` },
      }),
    ),
    true,
  );
  const received: Record<string, any[]> = { helper: [], one: [], two: [] };
  for (const id of ["helper", "one", "two"])
    broker.attach({
      id,
      role: id === "helper" ? "helper" : "ui",
      adminId: "admin",
      send: (v) => received[id].push(JSON.parse(v)),
      close: () => {},
    });
  const command = {
    id: "cmd1",
    operationId: "op1",
    clientId: "one",
    name: "device.reveal_secret",
    parameters: {},
    deviceId: "scale",
    connectionGeneration: 1,
  };
  assert.equal((await broker.command("other", command)).status, 409);
  assert.equal((await broker.command("admin", command)).status, 202);
  assert.equal(
    (
      await broker.command("admin", {
        ...command,
        parameters: { changed: true },
      })
    ).status,
    409,
  );
  broker.message(
    "helper",
    JSON.stringify({
      protocol: "yow.bridge",
      version: 1,
      kind: "result",
      id: "cmd1",
      operationId: "op1",
      name: "device.reveal_secret",
      result: { secret: "synthetic" },
      replyTo: "one",
    }),
  );
  assert.equal(received.one.at(-1).result.secret, "synthetic");
  assert.ok(!JSON.stringify(received.two).includes("synthetic"));
  assert.ok(!JSON.stringify(broker.status()).includes("synthetic"));
  assert.equal(broker.operations.size, 0);
  await broker.revoke();
  assert.equal(broker.helper(), undefined);
  assert.equal(
    await broker.helperAuthorized(
      new Request(origin, {
        headers: { Authorization: `Bearer ${first.credential}` },
      }),
    ),
    false,
  );
});
