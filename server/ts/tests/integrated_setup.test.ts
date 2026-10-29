import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LocalSqlite } from "../sqlite.ts";
import { handleApp, type AppEnv } from "../app.ts";
import { BridgeBroker } from "../bridge.ts";
const origin = "https://household.test";
const baseline = JSON.parse(
  readFileSync(
    new URL(
      "../../../contracts/withings/ws30-baseline.sanitized.json",
      import.meta.url,
    ),
    "utf8",
  ),
);
test("two-stage bootstrap, integrated navigation, automatic model-safe enrollment and shared Sync password", async () => {
  const dir = mkdtempSync(join(tmpdir(), "yow-integrated-")),
    store = new LocalSqlite(join(dir, "db.sqlite")),
    broker = new BridgeBroker();
  const env: AppEnv = {
    DB: store.asD1(),
    YOW_BOOTSTRAP_TOKEN: "test-bootstrap-0123456789abcdef",
    ALLOW_HTTP_SCALE: true,
    bridgeRequest: (r, a) => broker.http(r, a),
    captureWithings: async (scale) =>
      JSON.stringify({ ...baseline, mac: scale.mac }),
  };
  let cookie = "",
    csrf = "";
  const send = async (
    path: string,
    body?: URLSearchParams | Record<string, unknown>,
  ) => {
    const headers: Record<string, string> = { Cookie: cookie, Origin: origin };
    let bytes: string | undefined;
    if (body instanceof URLSearchParams) {
      headers["Content-Type"] = "application/x-www-form-urlencoded";
      body.set("_csrf", csrf);
      bytes = body.toString();
    } else if (body) {
      headers["Content-Type"] = "application/json";
      headers["X-CSRF-Token"] = csrf;
      bytes = JSON.stringify(body);
    }
    const r = await handleApp(
      new Request(origin + path, {
        method: body ? "POST" : "GET",
        headers,
        body: bytes,
      }),
      env,
    );
    if (r.headers.has("set-cookie"))
      cookie = r.headers.get("set-cookie")!.split(";")[0];
    return r;
  };
  const page = async (path: string) => {
    const r = await send(path),
      text = await r.text();
    csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(text)?.[1] ?? csrf;
    return text;
  };
  try {
    assert.match(await page("/setup"), /Bootstrap Token/);
    assert.equal(
      (
        await send(
          "/setup",
          new URLSearchParams({
            step: "bootstrap",
            bootstrap_token: env.YOW_BOOTSTRAP_TOKEN!,
          }),
        )
      ).status,
      303,
    );
    assert.match(await page("/setup"), /Set Your Password/);
    assert.equal(
      (
        await send(
          "/setup",
          new URLSearchParams({
            step: "password",
            password: "password123",
            confirm: "password123",
          }),
        )
      ).status,
      303,
    );
    const dashboard = await page("/");
    assert.match(dashboard, /Add Your First Scale/);
    assert.doesNotMatch(dashboard, />Admin<|Device Config/);
    const scales = await page("/scales");
    assert.match(scales, /<h1>Scales<\/h1>/);
    assert.doesNotMatch(scales, /firmware-workspace/);
    assert.match(await page("/firmware"), /Connect The Python Bridge/);
    assert.doesNotMatch(scales, />Registered Devices</);
    const record = (model: string, mac: string) => ({
      format:
        model === "WBS06"
          ? "YOW-BLE-device-v1"
          : "YOW-Classic-device-v1",
      model,
      name: model === "WBS06" ? "Body" : "WS-30",
      mac,
      session_secret: "0123456789abcdef",
      hardware_version: 0xffffff,
      bootloader_version: model === "WBS06" ? 4 : 15,
      firmware_version: model === "WBS06" ? 127 : 102,
      rescue_version: 0xffffff,
      captured_at: Math.floor(Date.now() / 1000),
    });
    const result = await send("/api/scales/enroll", {
      device: record("WBS06", "020000000006"),
      timeZone: "Europe/Berlin",
    });
    assert.equal(result.status, 200, await result.clone().text());
    const preview = (await result.json()) as any;
    assert.equal(preview.users.length, 4);
    assert.equal(preview.settingsReady, true);
    const savedFirmware = await store
      .prepare("SELECT firmware_version,firmware_source FROM scales WHERE id=?")
      .bind(preview.scaleId)
      .first<any>();
    assert.equal(savedFirmware.firmware_version, 127);
    assert.equal(savedFirmware.firmware_source, "bluetooth");
    const observationPath = `/api/scales/${preview.scaleId}/firmware-observation`;
    const observation = {
      mac: "020000000006",
      model: "WBS06",
      firmwareVersion: 126,
      observedAt: new Date().toISOString(),
    };
    assert.equal((await send(observationPath, observation)).status, 200);
    assert.equal(
      (
        await store
          .prepare("SELECT firmware_version FROM scales WHERE id=?")
          .bind(preview.scaleId)
          .first<any>()
      ).firmware_version,
      126,
    );
    assert.equal(
      (await send(observationPath, { ...observation, mac: "020000000003" }))
        .status,
      400,
    );
    assert.equal(
      (await send(observationPath, { ...observation, observedAt: "invalid" }))
        .status,
      400,
    );
    assert.equal(
      (
        await send(observationPath, {
          ...observation,
          firmwareVersion: 0xffffff,
        })
      ).status,
      400,
    );

    const imported = await send(`/api/scales/${preview.scaleId}/import-users`, {
      digest: preview.digest,
      userIds: [preview.users[0].id, preview.users[1].id],
    });
    assert.equal(imported.status, 200, await imported.clone().text());
    await store
      .prepare(
        "UPDATE users SET name='Locally Edited',short_name='EDT' WHERE id=?",
      )
      .bind(preview.users[0].id)
      .run();
    const ws = (await (
      await send("/api/scales/enroll", {
        device: record("WBS03", "020000000003"),
        timeZone: "Europe/Berlin",
      })
    ).json()) as any;
    assert.equal(ws.users.length, 2);
    assert.equal(ws.settingsReady, true);
    const dbws = await store
      .prepare("SELECT * FROM scales WHERE model='WBS03'")
      .first<any>();
    assert.equal(dbws.screen_response, null);
    assert.equal(dbws.summary_response, null);
    assert.equal(dbws.settings_ready, 0);
    assert.equal(dbws.roster_enabled, 0);
    assert.equal(
      (
        await store
          .prepare("SELECT name FROM users WHERE id=?")
          .bind(preview.users[0].id)
          .first<any>()
      ).name,
      "Locally Edited",
    );
    const api = await handleApp(
      new Request(`${origin}/api/users/${preview.users[0].id}/weights`, {
        headers: { Authorization: `Basic ${btoa("reader:password123")}` },
      }),
      env,
    );
    assert.equal(api.status, 200);
    const time = (await (
      await send("/api/config/time?zone=Europe%2FBerlin")
    ).json()) as any;
    assert.ok(time.utcSeconds > 0);
    assert.ok([3600, 7200].includes(time.goff));
    assert.equal(
      (
        await send(`/api/scales/${preview.scaleId}/time-zone`, {
          timeZone: "Asia/Kolkata",
        })
      ).status,
      200,
    );
    assert.equal(
      (
        await store
          .prepare("SELECT time_zone FROM scales WHERE id=?")
          .bind(preview.scaleId)
          .first<any>()
      ).time_zone,
      "Asia/Kolkata",
    );
    assert.equal(
      (
        await send(`/api/scales/${preview.scaleId}/time-zone`, {
          timeZone: "Invalid/Zone",
        })
      ).status,
      400,
    );
    const devicesPage = await page("/scales");
    assert.match(devicesPage, /Edit Settings/);
    assert.match(devicesPage, /data-timezone-select/);
    assert.ok(
      devicesPage.indexOf('class="page-footer"') >
        devicesPage.indexOf('class="scale-cards"'),
    );
    const beforeEdit = await store
      .prepare(
        "SELECT settings_ready,roster_enabled,screen_response,summary_response FROM scales WHERE id=?",
      )
      .bind(preview.scaleId)
      .first<any>();
    const edited = await send(
      `/scales/${preview.scaleId}`,
      new URLSearchParams({
        purpose: "device_config",
        label: "Renamed Scale",
        time_zone: "Europe/London",
        goff: "3600",
        dst: "0",
        ngoff: "0",
        feature_mask: "3",
        beta_ws: "0",
        temp_code: "11",
        weight_code: "1",
      }),
    );
    assert.equal(edited.status, 303);
    assert.deepEqual(
      await store
        .prepare(
          "SELECT settings_ready,roster_enabled,screen_response,summary_response FROM scales WHERE id=?",
        )
        .bind(preview.scaleId)
        .first<any>(),
      beforeEdit,
    );
    assert.equal(
      (
        await store
          .prepare("SELECT label FROM scales WHERE id=?")
          .bind(preview.scaleId)
          .first<any>()
      ).label,
      "Renamed Scale",
    );
    assert.doesNotMatch(
      await page("/scales"),
      /Confirm Settings|Settings Unconfirmed|Enable Scale Sync|Read-only Withings Capture/,
    );
    assert.match(await page("/sync"), /configure it on your Mac/);
    const invitation = await send("/api/bridge/invitations", {});
    assert.equal(invitation.status, 200);
    const noCsrf = await handleApp(
      new Request(origin + "/api/bridge/invitations", {
        method: "POST",
        headers: {
          Cookie: cookie,
          Origin: origin,
          "Content-Type": "application/json",
        },
        body: "{}",
      }),
      env,
    );
    assert.equal(noCsrf.status, 403);
  } finally {
    store.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
