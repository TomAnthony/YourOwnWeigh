/** Exercise the real browser controller with a minimal DOM/socket harness.
 * No Bluetooth, network requests or firmware writes occur in these tests. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { firmwareWorkspace } from "../integrated_ui.ts";

function browser(classification: string | undefined) {
  const element = (): any => ({
    hidden: false,
    disabled: false,
    value: "",
    textContent: "",
    options: [],
    dataset: {},
    classList: { toggle() {}, add() {} },
    append() {},
    replaceChildren() {},
    setAttribute() {},
    addEventListener() {},
    querySelectorAll: () => [],
    remove() {},
    showModal() {
      this.open = true;
    },
    close() {
      this.open = false;
    },
  });
  // Use actual rendered IDs so new controller dependencies cannot silently pass.
  const elements = new Map(
    [...firmwareWorkspace("test-csrf").matchAll(/\bid="([^"]+)"/g)].map(
      (match) => [match[1], element()],
    ),
  );
  const get = (id: string): any => {
    assert.ok(elements.has(id), `Missing rendered element: ${id}`);
    return elements.get(id);
  };
  get("scale-model").value = "WBS13";
  let socket: any;
  const emit = (data: any) => socket.onmessage({ data: JSON.stringify(data) });
  const commands: any[] = [];
  const artifact = {
    artifactId: "fixture",
    filename: "custom.bin",
    version: 104,
    model: "WBS13",
    size: 1200,
    sha256: "a".repeat(64),
    classification,
  };
  runInNewContext(
    readFileSync(new URL("../../static/firmware.js", import.meta.url), "utf8"),
    {
      document: { getElementById: get, createElement: element },
      location: new URL("https://example.test/firmware"),
      crypto,
      setTimeout: () => 1,
      clearTimeout() {},
      WebSocket: class {
        constructor() {
          socket = this;
        }
      },
      fetch: async (path: string, init: any) => {
        if (path === "/api/devices")
          return { ok: true, json: async () => ({ devices: [] }) };
        assert.equal(path, "/api/bridge/commands");
        const command = JSON.parse(init.body);
        commands.push(command);
        if (command.name === "artifact.begin")
          queueMicrotask(() =>
            emit({
              kind: "error",
              id: command.id,
              error: { message: "Rejected Test Upload" },
            }),
          );
        else {
          assert.equal(command.name, "firmware.install");
          queueMicrotask(() =>
            emit({
              kind: "result",
              id: command.id,
              result: { transferred: true },
            }),
          );
        }
        return { ok: true, json: async () => ({ accepted: true }) };
      },
    },
  );
  emit({
    kind: "ready",
    clientId: "browser",
    connected: true,
    snapshot: {
      state: "connected",
      deviceId: "test-scale",
      connectionGeneration: 1,
      device: {
        model: "WBS13",
        mac: "020000000013",
        firmwareVersion: 100,
        capabilities: { ota: true },
      },
      artifacts: [artifact],
      candidates: [],
    },
  });
  return { get, commands, artifact };
}

for (const classification of [
  "custom",
  undefined,
  "known_release",
  "known_stock",
]) {
  test(`firmware dialog and submitted consent match ${classification ?? "missing classification"}`, async () => {
    const { get, commands, artifact } = browser(classification);
    const unknown = classification === "custom" || classification === undefined;
    const phrase = unknown ? "FLASH UNKNOWN" : "FLASH";
    assert.equal(get("firmware-warning").hidden, !unknown);
    if (unknown)
      assert.match(get("firmware-info").textContent, /Unknown Firmware/);
    get("install-firmware").onclick();
    assert.equal(get("flash-warning").hidden, !unknown);
    assert.equal(get("flash-prompt").textContent, `Type ${phrase}`);
    assert.ok(get("flash-summary").textContent.includes(artifact.sha256));
    assert.equal(get("confirm-flash").disabled, true);
    for (const input of [
      unknown ? "FLASH" : "FLASH UNKNOWN",
      phrase.toLowerCase(),
      `${phrase} `,
    ]) {
      get("flash-confirmation").value = input;
      get("flash-confirmation").oninput();
      assert.equal(get("confirm-flash").disabled, true);
      await get("confirm-flash").onclick(); // Guard must also hold without the disabled button.
      assert.equal(commands.length, 0);
    }
    get("flash-confirmation").value = phrase;
    get("flash-confirmation").oninput();
    assert.equal(get("confirm-flash").disabled, false);
    await get("confirm-flash").onclick();
    assert.equal(commands.length, 1);
    assert.deepEqual(commands[0].parameters, {
      artifactId: artifact.artifactId,
      sha256: artifact.sha256,
      confirmation: phrase,
    });
  });
}

test("a rejected manual upload clears the previous flashable selection", async () => {
  const { get, commands } = browser("known_release");
  get("install-firmware").onclick();
  get("manual-firmware").files = [
    {
      name: "bad.bin",
      size: 256,
      arrayBuffer: async () => new ArrayBuffer(256),
    },
  ];
  await get("manual-firmware").onchange();
  assert.equal(get("install-firmware").disabled, true);
  assert.equal(get("firmware-info").hidden, true);
  assert.equal(get("firmware-warning").hidden, true);
  get("flash-confirmation").value = "FLASH";
  await get("confirm-flash").onclick();
  assert.equal(
    commands.some((command) => command.name === "firmware.install"),
    false,
  );
});
