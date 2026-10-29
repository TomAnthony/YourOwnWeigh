/** Developer-only end-to-end test. Uses a NEW loopback test installation and
 * Python --simulate: no Bluetooth, vendor requests, real firmware writes or cloud
 * deployment. Run against Node or wrangler dev after applying migrations.
 * YOW_TEST_URL=http://127.0.0.1:PORT YOW_TEST_BOOTSTRAP=... YOW_TEST_PYTHON=... node tools/check_bridge_integration.mjs
 */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import WebSocket from "ws";
const base = process.env.YOW_TEST_URL,
  bootstrap = process.env.YOW_TEST_BOOTSTRAP,
  python = process.env.YOW_TEST_PYTHON;
if (!base || new URL(base).hostname !== "127.0.0.1" || !bootstrap || !python)
  throw new Error(
    "Use a fresh loopback fixture and provide all three YOW_TEST variables.",
  );
let cookie = "",
  csrf = "";
async function request(path, body, form = false) {
  const r = await fetch(base + path, {
    redirect: "manual",
    method: body ? "POST" : "GET",
    headers: {
      Cookie: cookie,
      Origin: base,
      ...(body
        ? form
          ? { "Content-Type": "application/x-www-form-urlencoded" }
          : { "Content-Type": "application/json", "X-CSRF-Token": csrf }
        : {}),
    },
    body: body
      ? form
        ? new URLSearchParams({ ...body, _csrf: csrf })
        : JSON.stringify(body)
      : undefined,
  });
  if (r.headers.has("set-cookie"))
    cookie = r.headers.get("set-cookie").split(";")[0];
  return r;
}
let setup = await request("/setup"),
  html;
if (setup.status === 303) {
  html = await (await request("/login")).text();
  csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(html)?.[1];
  assert.ok(csrf);
  assert.equal(
    (await request("/login", { password: "integration-test-only" }, true))
      .status,
    303,
  );
} else {
  html = await setup.text();
  csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(html)?.[1];
  assert.ok(csrf);
  assert.equal(
    (
      await request(
        "/setup",
        { step: "bootstrap", bootstrap_token: bootstrap },
        true,
      )
    ).status,
    303,
  );
  html = await (await request("/setup")).text();
  csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(html)?.[1];
  assert.ok(csrf);
  assert.equal(
    (
      await request(
        "/setup",
        { password: "integration-test-only", confirm: "integration-test-only" },
        true,
      )
    ).status,
    303,
  );
}
html = await (await request("/scales")).text();
csrf = /name="csrf-token" content="([a-f0-9]+)"/.exec(html)?.[1];
assert.ok(csrf);
const invitation = await (await request("/api/bridge/invitations", {})).json();
assert.ok(
  invitation.token || invitation.invitation?.token,
  JSON.stringify(invitation),
);
const state = mkdtempSync(join(tmpdir(), "yow-bridge-e2e-"));
const helper = spawn(
  python,
  ["-m", "yow_bridge", "--simulate", "--state-dir", state],
  { stdio: ["pipe", "pipe", "pipe"] },
);
helper.stdin.end(JSON.stringify(invitation.invitation ?? invitation) + "\n");
let output = "";
helper.stderr.on("data", (d) => {
  output += d;
});
helper.stdout.on("data", (d) => {
  output += d;
});
let ws, clientId, readyResolve;
let latestStatus, latestOperation;
const ready = new Promise((resolve) => (readyResolve = resolve)),
  pending = new Map();
function open() {
  return new Promise((resolve, reject) => {
    ws = new WebSocket(base.replace("http:", "ws:") + "/api/bridge/ui/socket", {
      headers: { Cookie: cookie, Origin: base },
    });
    ws.on("error", reject);
    ws.on("message", (raw) => {
      const event = JSON.parse(raw);
      if (["ready", "connection"].includes(event.kind)) latestStatus = event;
      if (event.kind === "operation") latestOperation = event.operation;
      if (event.kind === "ready") {
        clientId = event.clientId;
        resolve();
      }
      if (
        (event.kind === "ready" || event.kind === "connection") &&
        event.connected
      )
        readyResolve();
      if (["result", "error"].includes(event.kind) && pending.has(event.id)) {
        const p = pending.get(event.id);
        pending.delete(event.id);
        event.kind === "error"
          ? p.reject(new Error(JSON.stringify(event.error)))
          : p.resolve(event.result);
      }
    });
  });
}
async function command(name, parameters = {}, extra = {}) {
  const id = crypto.randomUUID();
  const answer = new Promise((resolve, reject) =>
    pending.set(id, { resolve, reject }),
  );
  const result = await request("/api/bridge/commands", {
    id,
    operationId: crypto.randomUUID(),
    clientId,
    name,
    parameters,
    ...extra,
  });
  assert.equal(result.status, 202, await result.text());
  return Promise.race([
    answer,
    new Promise((_, reject) => {
      const t = setTimeout(
        () => reject(new Error("Timed out: " + name)),
        20000,
      );
      t.unref();
    }),
  ]);
}
try {
  await open();
  await Promise.race([
    ready,
    new Promise((_, reject) => {
      const t = setTimeout(
        () => reject(new Error("Helper not connected: " + output)),
        15000,
      );
      t.unref();
    }),
  ]);
  for (const model of ["WBS06", "WBS03"]) {
    const scan = await command("device.scan.start", {
      model,
      durationSeconds: 1,
    });
    assert.ok(scan.candidates.length);
    const connection = await command(
      "device.connect",
      {},
      { deviceId: scan.candidates[0].deviceId },
    );
    const extra = {
      deviceId: scan.candidates[0].deviceId,
      connectionGeneration: connection.connectionGeneration,
    };
    const probe = await command("device.probe", {}, extra);
    assert.equal(probe.model, model);
    const record = await command(
      "device.enroll",
      { approved: true, label: "Demo", timeZone: "Europe/Berlin" },
      extra,
    );
    assert.equal(record.device.model, model);
    const secret = await command("device.reveal_secret", {}, extra);
    assert.equal(secret.secret, "0123456789abcdef");
    const time = await (
      await request("/api/config/time?zone=Europe%2FBerlin")
    ).json();
    await command("device.set_time", time, extra);
    await command("device.complete_setup", {}, extra);
    await command("device.disconnect", {}, extra);
  }
  // Browser reconnect: the helper and pairing remain alive.
  ws.close();
  await open();
  assert.ok((await command("bridge.describe")).simulated);
  if (process.env.YOW_TEST_RECOVERY === "1") {
    // This extension uses only synthetic wire events, no physical scale or OTA.
    // Leave the browser connected while replacing/stalling its helper socket.
    const exited = new Promise((resolve) => helper.once("exit", resolve));
    helper.kill("SIGTERM");
    await exited;
    const pairing = JSON.parse(
      readFileSync(join(state, "pairing.json"), "utf8"),
    );
    async function until(check, timeout = 5000) {
      const end = Date.now() + timeout;
      while (!check()) {
        if (Date.now() > end)
          throw new Error("Recovery status did not converge");
        await new Promise((resolve) => setTimeout(resolve, 25));
      }
    }
    await until(() => latestStatus?.connected === false);
    const openHelper = async () => {
      const sock = new WebSocket(
        base.replace("http:", "ws:") + "/api/bridge/socket",
        {
          headers: {
            Authorization: `Bearer ${pairing.credential}`,
            "X-YOW-Bridge-Run": "synthetic-reconnect-test",
          },
        },
      );
      await new Promise((resolve, reject) => {
        sock.once("open", resolve);
        sock.once("error", reject);
      });
      sock.send(
        JSON.stringify({
          protocol: "yow.bridge",
          version: 1,
          kind: "hello",
          snapshot: { simulated: true },
        }),
      );
      return sock;
    };
    const old = await openHelper();
    const oldClosed = new Promise((resolve) => old.once("close", resolve));
    const replacement = await openHelper();
    await oldClosed;
    const progress = {
      operationId: "synthetic-ota",
      name: "firmware.install",
      state: "running",
      stage: "transferring",
      bytesDone: 500,
      bytesTotal: 1000,
    };
    replacement.send(
      JSON.stringify({
        protocol: "yow.bridge",
        version: 1,
        kind: "progress",
        name: "firmware.install",
        operationId: progress.operationId,
        progress,
      }),
    );
    await until(() => latestOperation?.bytesDone === 500);
    ws.close();
    await open();
    assert.equal(latestStatus.snapshot.activeOperation.bytesDone, 500);
    // Stop application heartbeats without closing TCP. Browser must become
    // disconnected within the 45-second lease, including in a Durable Object.
    console.log(
      "Recovery: replacement and refreshed OTA progress passed; checking silent-helper expiry (45 seconds)…",
    );
    await until(() => latestStatus?.connected === false, 52_000);
    replacement.close();
    console.log(
      "PASS: same-process socket replacement, refreshed OTA progress and silent-helper expiry.",
    );
  }
  console.log(
    "PASS: real WebSocket pairing, both simulated models, private export, server clock, complete setup and browser reconnect.",
  );
} finally {
  ws?.close();
  if (helper.exitCode === null && helper.signalCode === null) {
    helper.kill("SIGTERM");
    await new Promise((resolve) => helper.once("exit", resolve));
  }
  rmSync(state, { recursive: true, force: true });
}
