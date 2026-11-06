/** Exercise the real browser controller with a minimal DOM/socket harness.
 * No Bluetooth, network requests or firmware writes occur in these tests. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { firmwareWorkspace } from "../integrated_ui.ts";
import { SCALE_MODELS } from "../models.ts";

function browser(
  classification: string | undefined,
  model = "WBS13",
  releaseStatus?: string,
  wifiResult?: { joinStatus: string; storedSsidMatches: boolean },
  knownDevices: Record<string, unknown>[] = [],
) {
  const element = (): any => ({
    hidden: false,
    disabled: false,
    value: "",
    textContent: "",
    options: [],
    dataset: {},
    classList: { toggle() {}, add() {} },
    children: [],
    append(...children: any[]) { this.children.push(...children); },
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
  get("scale-model").value = model;
  get("firmware-workspace").dataset.localRosterModels =
    /data-local-roster-models="([^"]*)"/.exec(firmwareWorkspace("test-csrf"))![1];
  let socket: any;
  const emit = (data: any) => socket.onmessage({ data: JSON.stringify(data) });
  const commands: any[] = [];
  const device = {
    model, mac: "020000000013", firmwareVersion: 100,
    capabilities: { ota: true, enrollment: true },
  };
  const artifact = {
    artifactId: "fixture",
    filename: "custom.bin",
    version: model === "WBS05" ? 100 : 104,
    model,
    size: 1200,
    sha256: "a".repeat(64),
    classification,
    releaseStatus,
  };
  runInNewContext(
    readFileSync(new URL("../../static/firmware.js", import.meta.url), "utf8"),
    {
      document: {
        getElementById: get,
        createElement: element,
        createTextNode: (text: string) => ({ textContent: text }),
      },
      location: new URL("https://example.test/firmware"),
      crypto,
      setTimeout: () => 1,
      clearTimeout() {},
      clearInterval() {},
      WebSocket: class {
        constructor() {
          socket = this;
        }
      },
      fetch: async (path: string, init: any) => {
        if (path === "/api/devices")
          return { ok: true, json: async () => ({ devices: knownDevices }) };
        if (/^\/api\/scales\/\d+\/firmware-observation$/.test(path))
          return { ok: true, json: async () => ({ saved: true }) };
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
        else if (command.name === "device.scan.start")
          queueMicrotask(() =>
            emit({
              kind: "result",
              id: command.id,
              result: { candidates: [] },
            }),
          );
        else if (command.name === "device.probe")
          queueMicrotask(() => emit({ kind: "result", id: command.id, result: device }));
        else if (command.name === "device.connect_wifi")
          queueMicrotask(() =>
            emit({ kind: "result", id: command.id, result: wifiResult }),
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
      device,
      artifacts: [artifact],
      candidates: [],
    },
  });
  return { get, commands, artifact, emit, device };
}

for (const [model, profile] of Object.entries(SCALE_MODELS)) {
  test(`${model}: new scale prompts for import and keeps a manual import link`, async () => {
    const { get } = browser("known_release", model);
    await get("probe").onclick();
    assert.equal(get("enroll-dialog").open, true);
    assert.equal(get("import-device").hidden, false);
    assert.equal(get("import-device").disabled, false);
    assert.match(get("enroll-description").textContent, profile.localRoster
      ? /choose its local users/ : /check Withings/);
    get("enroll-dialog").close();
    await get("probe").onclick();
    assert.equal(get("enroll-dialog").open, false, "Do not repeat an already dismissed prompt");
    get("import-device").onclick();
    assert.equal(get("enroll-dialog").open, true);
  });
  test(`${model}: registered scale does not prompt for import again`, async () => {
    const { get } = browser("known_release", model, undefined, undefined,
      [{ id: 1, model, mac: "020000000013" }]);
    await get("probe").onclick();
    assert.notEqual(get("enroll-dialog").open, true);
  });
}

test("an older bridge's explicit enrollment restriction is respected", async () => {
  const { get, device } = browser("known_release", "WBS05");
  device.capabilities.enrollment = false;
  await get("probe").onclick();
  assert.notEqual(get("enroll-dialog").open, true);
  assert.equal(get("import-device").hidden, true);
});

for (const joined of [true, false]) {
  for (const ssidMatches of [true, false]) {
    test(`Wi-Fi status distinguishes join=${joined} from SSID match=${ssidMatches}`, async () => {
      const { get, commands } = browser("known_release", "WBS05", "candidate", {
        joinStatus: joined ? "success" : "failed",
        storedSsidMatches: ssidMatches,
      });
      get("wifi-ssid").value = "Test Network";
      get("wifi-password").value = "synthetic-password";
      await get("wifi-form").onsubmit({ preventDefault() {} });
      assert.equal(commands.length, 1);
      assert.equal(commands[0].name, "device.connect_wifi");
      assert.deepEqual(commands[0].parameters, {
        ssid: "Test Network", password: "synthetic-password",
      });
      assert.equal(get("wifi-password").value, "");
      assert.equal(get("wifi-password").placeholder, "");
      assert.match(get("wifi-password-hint").textContent, /saving it has not been verified/);
      assert.equal(get("wifi-status").textContent, joined
        ? ssidMatches ? "Wi-Fi Connected · Stored SSID Matches" : "Wi-Fi Connected · Stored SSID Not Confirmed"
        : "Wi-Fi Connection Failed · Check Credentials And 2.4 GHz WPA2 Network");
      const toast = get("toast-region").children.at(-1);
      assert.equal(toast.className, joined && ssidMatches ? "toast" : "toast toast-error");
      assert.match(toast.children[1].textContent, !joined
        ? /Connection Failed/ : ssidMatches ? /password was saved is unverified/ : /stored SSID could not be confirmed/);
    });
  }
}

test("a successful same-SSID password change never claims credential persistence", async () => {
  // WBS05 may join using the new password yet retain its old credentials if
  // the subsequent server probe fails. Both attempts have identical readback.
  const { get, commands } = browser("known_release", "WBS05", "candidate", {
    joinStatus: "success", storedSsidMatches: true,
  });
  get("wifi-ssid").value = "Existing Network";
  get("wifi-password").placeholder = "••••••";
  for (const password of ["original-password", "replacement-password"]) {
    get("wifi-password").value = password;
    await get("wifi-form").onsubmit({ preventDefault() {} });
    assert.deepEqual(commands.at(-1).parameters, { ssid: "Existing Network", password });
    const status = get("wifi-status").textContent;
    const toast = get("toast-region").children.at(-1).children[1].textContent;
    assert.match(status, /Stored SSID Matches/);
    assert.match(toast, /password was saved is unverified/);
    assert.doesNotMatch(`${status} ${toast}`, /settings saved|credentials saved|complete setup/i);
    assert.equal(get("wifi-password").value, "");
    assert.equal(get("wifi-password").placeholder, "");
  }
});

test("WBS05 candidate is labeled, uses FLASH, and allows enrollment", async () => {
  assert.match(firmwareWorkspace("test"), /value="WBS05">Body\+ \(WBS05\)/);
  const { get, commands } = browser("known_release", "WBS05", "candidate");
  assert.match(get("firmware-info").textContent, /v100.*YOW Candidate · Awaiting Hardware Test/);
  assert.match(get("generate-firmware").textContent, /Body\+ \(WBS05\)/);
  assert.equal(get("import-device").hidden, false);
  assert.equal(get("install-firmware").disabled, false);
  get("install-firmware").onclick();
  assert.equal(get("flash-prompt").textContent, "Type FLASH");
  get("flash-confirmation").value = "FLASH";
  get("flash-confirmation").oninput();
  await get("confirm-flash").onclick();
  assert.equal(commands[0].name, "firmware.install");
  assert.equal(commands[0].parameters.confirmation, "FLASH");
});

for (const simulated of [true, false]) {
  for (const [selected, family] of [
    ["WBS06", "ble"],
    ["WBS13", "ble"],
    ["WBS04", "ble"],
    ["WBS05", "ble"],
    ["WBS03", "classic"],
    ["WBS02", "classic"],
    ["UNKNOWN", "unknown"],
  ]) {
    for (const transport of ["ble", "classic"]) {
      test(`${simulated ? "simulated" : "real"} ${transport} scan with ${selected} selected`, async () => {
        const { get, commands, emit } = browser("known_release");
        emit({
          kind: "ready",
          clientId: "browser",
          connected: true,
          snapshot: { state: "disconnected", simulated, candidates: [] },
        });
        get("scale-model").value = selected;
        await get(`scan-${transport}`).onclick();
        const expected = simulated && family === transport
          ? selected
          : transport === "ble" ? "WBS06" : "WBS03";
        assert.equal(commands.length, 1);
        assert.equal(commands[0].name, "device.scan.start");
        assert.deepEqual(commands[0].parameters, {
          model: expected,
          durationSeconds: 15,
        });
        assert.equal(get("scale-model").value, expected);
      });
    }
  }
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
