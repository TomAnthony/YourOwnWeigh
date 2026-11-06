/** Enrollment must work for every released model/version, through both import
 * entrypoints. Synthetic identities only; vendor replies are local fixtures. */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LocalSqlite } from "../sqlite.ts";
import { handleApp, type AppEnv } from "../app.ts";
import { SCALE_MODELS } from "../models.ts";

test("all supported models import through the API and device file; local rosters never call Withings", async () => {
  const directory = mkdtempSync(join(tmpdir(), "yow-enrollment-"));
  const store = new LocalSqlite(join(directory, "test.db"));
  const db = store.asD1();
  const baseline = JSON.parse(readFileSync(new URL(
    "../../../contracts/withings/ws30-baseline.sanitized.json", import.meta.url,
  ), "utf8"));
  let cookie = "", csrf = "", vendorCalls = 0, nextMac = 1;
  const env: AppEnv = {
    DB: db,
    captureWithings: async (scale) => {
      assert.equal(SCALE_MODELS[scale.model].localRoster, false);
      vendorCalls++;
      return JSON.stringify({ ...baseline, mac: scale.mac });
    },
  };
  const web = async (path: string, body?: URLSearchParams | FormData | Record<string, unknown>) => {
    const headers: Record<string, string> = { Cookie: cookie, Origin: "http://localhost" };
    let data: BodyInit | undefined;
    if (body instanceof URLSearchParams || body instanceof FormData) {
      body.set("_csrf", csrf);
      data = body;
    } else if (body) {
      headers["Content-Type"] = "application/json";
      headers["X-CSRF-Token"] = csrf;
      data = JSON.stringify(body);
    }
    const response = await handleApp(new Request(`http://localhost${path}`, {
      method: body ? "POST" : "GET", headers, body: data,
    }), env);
    if (response.headers.has("Set-Cookie"))
      cookie = response.headers.get("Set-Cookie")!.split(";")[0];
    return response;
  };
  try {
    csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(await (await web("/setup")).text())![1];
    assert.equal((await web("/setup", new URLSearchParams({
      password: "test-password", confirm: "test-password",
    }))).status, 303);
    csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(await (await web("/")).text())![1];
    assert.deepEqual(SCALE_MODELS.WBS05.enrolledFirmware, [1651, 100]);
    assert.deepEqual(SCALE_MODELS.WBS13.enrolledFirmware, [100, 101, 102, 103]);
    for (const [model, profile] of Object.entries(SCALE_MODELS)) {
      for (const version of profile.enrolledFirmware) {
        const record = {
          format: profile.exportFormat, model,
          name: { WBS06: "Body", WBS03: "WS-30", WBS02: "Withings WS50",
            WBS04: "Body Cardio", WBS05: "Body+", WBS13: "Body Smart" }[model],
          mac: `020000${(nextMac++).toString(16).padStart(6, "0")}`,
          session_secret: "0123456789abcdef", hardware_version: 0xffffff,
          bootloader_version: profile.bootloader, firmware_version: version,
          rescue_version: 0xffffff, captured_at: Math.floor(Date.now() / 1000),
        };
        const before = vendorCalls;
        const response = await web("/api/scales/enroll", { device: record, timeZone: "Europe/Berlin" });
        assert.equal(response.status, 200, `${model} v${version}: ${await response.clone().text()}`);
        const result = await response.json() as any;
        assert.equal(result.localRoster === true, profile.localRoster);
        assert.equal(vendorCalls - before, profile.localRoster ? 0 : 1);
        assert.ok(result.scaleId);
        assert.notEqual(result.migrationIncomplete, true);
        const saved = await db.prepare("SELECT * FROM scales WHERE id=?").bind(result.scaleId).first<any>();
        assert.equal(saved.firmware_version, version);
        assert.equal(saved.firmware_source, "bluetooth");
        if (model === "WBS05")
          assert.deepEqual([saved.feature_mask, saved.temp_code, saved.weight_code], [3, 11, 1]);

        // Updating an existing device via its portable file must follow the
        // same policy, without duplicating the scale or resetting settings.
        const form = new FormData();
        form.set("record", new File([JSON.stringify(record)], "scale.yow-device.json", { type: "application/json" }));
        const uploaded = await web("/scales/import-ble", form);
        assert.equal(uploaded.status, 303);
        assert.match(uploaded.headers.get("Location")!, profile.localRoster ? /^\/scales/ : /^\/users/);
        for (const bad of [
          { firmware_version: 65535 }, { bootloader_version: profile.bootloader + 1 },
          { session_secret: "" }, ...(profile.transport === "ble" ? [{ hardware_version: 0 }] : []),
        ]) {
          const rejected = await web("/api/scales/enroll", { device: { ...record, ...bad } });
          assert.equal(rejected.status, 400, `${model} must reject ${JSON.stringify(bad)}`);
        }
      }
    }
    const scales = await (await web("/scales")).text();
    assert.match(scales, /Users On This Scale/);
    assert.match(scales, /Choose Users/);
    assert.doesNotMatch(scales, /Import Incomplete/);
    assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM scales").first<any>()).n, nextMac - 1);
  } finally {
    store.close();
    rmSync(directory, { recursive: true, force: true });
  }
});
