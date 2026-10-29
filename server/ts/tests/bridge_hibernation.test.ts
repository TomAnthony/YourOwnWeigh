/** Exercise socket reconstruction with Cloudflare-shaped objects, no cloud account. */
import test from "node:test";
import assert from "node:assert/strict";
import { BridgeDurableObject } from "../../cloudflare/bridge_do.ts";
import { BRIDGE_LEASE_MS } from "../bridge.ts";

function socket(
  id: string,
  role: "helper" | "ui",
  state: number,
  lastSeen: number,
) {
  let attachment = { id, role, lastSeen, runId: "same-process" };
  const sent: any[] = [];
  return {
    readyState: state,
    sent,
    deserializeAttachment: () => structuredClone(attachment),
    serializeAttachment: (value: typeof attachment) => {
      attachment = structuredClone(value);
    },
    send: (value: string) => sent.push(JSON.parse(value)),
    close: () => {},
  };
}

test("hibernation does not resurrect closing or heartbeat-expired helpers", async () => {
  for (const [state, age] of [
    [2, 0],
    [1, BRIDGE_LEASE_MS + 1000],
  ]) {
    const helper = socket("helper", "helper", state, Date.now() - age);
    const ui = socket("ui", "ui", 1, Date.now());
    const ctx = {
      blockConcurrencyWhile: (f: () => Promise<void>) => f(),
      getWebSockets: () => [ui, helper],
      storage: {
        get: async () => ({}),
        put: async () => {},
        getAlarm: async () => null,
        setAlarm: async () => {},
      },
    };
    const object = new BridgeDurableObject(ctx as any);
    await object.ready;
    assert.equal(object.broker.status().connected, false);
    assert.equal(object.broker.peers.has("helper"), false);
  }
});

test("application heartbeat persists its lease across Durable Object reconstruction", async () => {
  const helper = socket("helper", "helper", 1, Date.now() - 20_000);
  const ctx = {
    blockConcurrencyWhile: (f: () => Promise<void>) => f(),
    getWebSockets: () => [helper],
    storage: {
      get: async () => ({}),
      put: async () => {},
      getAlarm: async () => null,
      setAlarm: async () => {},
    },
  };
  const first = new BridgeDurableObject(ctx as any);
  await first.ready;
  await first.webSocketMessage(
    helper as any,
    JSON.stringify({ protocol: "yow.bridge", version: 1, kind: "ping" }),
  );
  assert.equal(helper.sent.at(-1).kind, "pong");
  assert.ok(Date.now() - helper.deserializeAttachment().lastSeen < 1000);
  const restored = new BridgeDurableObject(ctx as any);
  await restored.ready;
  assert.equal(restored.broker.status().connected, true);
});
