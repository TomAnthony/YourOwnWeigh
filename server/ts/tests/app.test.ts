import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LocalSqlite } from "../sqlite.ts";
import { handleApp, type AppEnv } from "../app.ts";

test("one TypeScript app serves dashboard, readings API and scale sync with SQLite", async () => {
  const directory = mkdtempSync(join(tmpdir(), "yow-ts-test-"));
  const store = new LocalSqlite(join(directory, "test.sqlite3"));
  const env: AppEnv = {
    DB: store.asD1(),
    ALLOW_HTTP_SCALE: true,
    YOW_BOOTSTRAP_TOKEN: "dummy-test-bootstrap-token",
  };
  let cookie = "";
  let csrf = "";
  const request = async (
    path: string,
    method = "GET",
    fields?: URLSearchParams,
    http = false,
  ): Promise<Response> => {
    const headers: Record<string, string> = {};
    if (cookie) headers.Cookie = cookie;
    if (fields) headers["Content-Type"] = "application/x-www-form-urlencoded";
    return handleApp(
      new Request(
        `${http ? "http://192.168.1.20" : "https://local.test"}${path}`,
        { method, headers, body: fields?.toString() },
      ),
      env,
    );
  };
  const post = async (
    path: string,
    fields: Record<string, string>,
  ): Promise<Response> =>
    request(path, "POST", new URLSearchParams({ _csrf: csrf, ...fields }));
  try {
    const first = await request("/setup");
    assert.equal(first.status, 200);
    cookie = first.headers.get("set-cookie")!.split(";")[0];
    csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(await first.text())![1];
    assert.equal(
      (
        await request(
          "/setup",
          "POST",
          new URLSearchParams({ password: "password-123" }),
        )
      ).status,
      403,
    );
    const setup = await post("/setup", {
      bootstrap_token: "dummy-test-bootstrap-token",
      password: "password-123",
      confirm: "password-123",
    });
    assert.equal(setup.status, 303);
    cookie = setup.headers.get("set-cookie")!.split(";")[0];
    const dashboard = await request("/");
    assert.equal(dashboard.status, 200);
    csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(await dashboard.text())![1];
    assert.match(
      await (await request("/settings")).text(),
      /Sync API Password/,
    );
    assert.equal(
      (await post("/settings", { purpose: "scale_api", action: "enable" }))
        .status,
      400,
    );
    assert.equal(
      (
        await request(
          "/once",
          "POST",
          new URLSearchParams({ action: "get" }),
          true,
        )
      ).status,
      200,
    );

    assert.equal(
      (
        await post("/scales", {
          label: "Bathroom",
          mac: "24:E4:2F:12:34:56",
          secret: "private-device-secret",
        })
      ).status,
      303,
    );
    assert.equal(
      (
        await post("/users", {
          name: "Sam",
          short_name: "SAM",
          height_cm: "181",
          age_years: "40",
          sex: "0",
          reference_weight_kg: "73",
          scales: "1",
        })
      ).status,
      303,
    );
    assert.equal(
      (
        await post("/scales/1", {
          purpose: "fixture",
          endpoint: "screen",
          fixture: '{"status":0,"body":{"device":[],"user":[]}}',
        })
      ).status,
      303,
    );
    assert.equal(
      (
        await post("/scales/1", {
          purpose: "fixture",
          endpoint: "summary",
          fixture: '{"status":0,"body":[]}',
        })
      ).status,
      303,
    );
    assert.equal(
      (
        await post("/scales/1", {
          purpose: "config",
          label: "Bathroom",
          time_zone: "Europe/Berlin",
          goff: "3600",
          dst: "0",
          ngoff: "3600",
          feature_mask: "7",
          beta_ws: "0",
          temp_code: "13",
          weight_code: "14",
          settings_ready: "1",
        })
      ).status,
      303,
    );
    assert.match(
      await (await request("/scales")).text(),
      /class="badge">Ready</,
    );
    assert.match(await (await request("/users")).text(), /Sam/);
    assert.match(
      await (await request("/settings")).text(),
      /Sync API Password/,
    );

    const once = await request(
      "/once",
      "POST",
      new URLSearchParams({ action: "get" }),
      true,
    );
    assert.equal(once.status, 200);
    const nonce = ((await once.json()) as { body: { once: string } }).body.once;
    const hash = Array.from(
      new Uint8Array(
        await crypto.subtle.digest(
          "SHA-256",
          new TextEncoder().encode(
            `24:E4:2F:12:34:56:private-device-secret:${nonce}`,
          ),
        ),
      ),
      (b) => b.toString(16).padStart(2, "0"),
    ).join("");
    const session = await request(
      "/session",
      "POST",
      new URLSearchParams({
        action: "new",
        auth: "24:E4:2F:12:34:56",
        hash,
        hashmethod: "sha256",
      }),
      true,
    );
    assert.equal(session.status, 200, await session.clone().text());
    const sid = ((await session.json()) as { body: { sessionid: string } }).body
      .sessionid;
    const measure = new URLSearchParams({
      action: "batchstore",
      sessionid: sid,
      macaddress: "24:E4:2F:12:34:56",
      userid: "1",
      devtype: "1",
      category: "1",
      attribstatus: "0",
      measuregrps: JSON.stringify({
        measuregrps: [
          {
            meastime: Math.floor(Date.now() / 1000),
            measures: [{ value: 73250, type: 1, unit: -3 }],
          },
        ],
      }),
    });
    assert.equal(
      (await request("/measure", "POST", measure, true)).status,
      200,
    );
    assert.equal(
      (await request("/measure", "POST", measure, true)).status,
      200,
    );
    assert.match(await (await request("/")).text(), /73\.25 kg/);
    assert.match(await (await request("/readings")).text(), /73\.25 kg/);
    assert.match(await (await request("/readings")).text(), /Not Acknowledged/);
    const api = await handleApp(
      new Request("https://local.test/api/users/1/weights", {
        headers: { Authorization: `Basic ${btoa("reader:reader-password")}` },
      }),
      env,
    );
    assert.equal(api.status, 401);
    assert.equal(
      (
        await post("/settings", {
          purpose: "api_password",
          current_admin: "password-123",
          new: "reader-password",
          confirm: "reader-password",
        })
      ).status,
      303,
    );
    const healthUrl = "https://local.test/api/users/1/health-sync";
    const healthAuth = {
      Authorization: `Basic ${btoa("reader:reader-password")}`,
    };
    const namedWeights = await handleApp(
      new Request("https://local.test/api/users/sam/weights", {
        headers: healthAuth,
      }),
      env,
    );
    assert.equal(namedWeights.status, 200);
    const namedData = (await namedWeights.json()) as {
      user: { id: number };
      readings: {
        weight_kg: string;
        health_sync_acknowledged_at: string | null;
      }[];
    };
    assert.equal(namedData.user.id, 1);
    assert.equal(namedData.readings[0].health_sync_acknowledged_at, null);
    assert.equal(
      (
        await handleApp(
          new Request("https://local.test/api/users/1/weights", {
            headers: healthAuth,
          }),
          env,
        )
      ).status,
      200,
    );
    assert.equal(
      (
        await handleApp(
          new Request("https://local.test/api/users/SAM/weights"),
          env,
        )
      ).status,
      401,
    );
    assert.equal(
      (
        await handleApp(
          new Request("https://local.test/api/users/XYZ/weights", {
            headers: healthAuth,
          }),
          env,
        )
      ).status,
      404,
    );
    const pending = await handleApp(
      new Request(
        "https://local.test/api/users/SAM/health-sync/next?since=1970-01-01",
        { headers: healthAuth },
      ),
      env,
    );
    assert.equal(pending.status, 200);
    const entry = (await pending.json()) as {
      reading: { id: number; weight_kg: string; date: string };
    };
    assert.equal(entry.reading.weight_kg, "73.250");
    assert.ok(entry.reading.date);
    assert.equal(
      (
        await handleApp(
          new Request(
            `https://local.test/api/users/sam/health-sync/ack?reading_id=${entry.reading.id}`,
            {
              method: "POST",
              headers: healthAuth,
            },
          ),
          env,
        )
      ).status,
      200,
    );
    assert.doesNotMatch(await (await request("/")).text(), /Health Sync/);
    for (const path of ["/readings", "/users/1/readings"]) {
      const page = await (await request(path)).text();
      assert.match(page, /<span class="badge">Acknowledged<\/span>/);
      assert.match(page, /<time class="hint" datetime="\d{4}-\d\d-\d\dT/);
    }
    const afterAck = (await (
      await handleApp(
        new Request("https://local.test/api/users/SAM/weights", {
          headers: healthAuth,
        }),
        env,
      )
    ).json()) as { readings: { health_sync_acknowledged_at: string | null }[] };
    assert.match(
      afterAck.readings[0].health_sync_acknowledged_at ?? "",
      /^\d{4}-\d\d-\d\dT/,
    );
    assert.equal(
      (
        (await (
          await handleApp(
            new Request(`${healthUrl}/next`, { headers: healthAuth }),
            env,
          )
        ).json()) as { reading: unknown }
      ).reading,
      null,
    );
    assert.equal(
      (
        await handleApp(
          new Request(`${healthUrl}/next?since=2026-02-30`, {
            headers: healthAuth,
          }),
          env,
        )
      ).status,
      400,
    );
    assert.equal((await request("/", "GET", undefined, true)).status, 308);
    const count = await store
      .asD1()
      .prepare("SELECT COUNT(*) AS count FROM readings")
      .first<{ count: number }>();
    assert.equal(count?.count, 1);
    assert.equal(
      (await post("/settings", { purpose: "scale_api", action: "disable" }))
        .status,
      400,
    );
    assert.equal(
      (
        await request(
          "/once",
          "POST",
          new URLSearchParams({ action: "get" }),
          true,
        )
      ).status,
      200,
    );
    assert.equal(
      (await post("/settings", { purpose: "scale_api", action: "enable" }))
        .status,
      400,
    );
    assert.equal(
      (
        await request(
          "/once",
          "POST",
          new URLSearchParams({ action: "get" }),
          true,
        )
      ).status,
      200,
    );
    assert.equal(
      (
        await post("/users", {
          name: "Other Sam",
          short_name: "SAM",
          height_cm: "180",
          age_years: "41",
          sex: "0",
          reference_weight_kg: "75",
        })
      ).status,
      303,
    );
    const ambiguous = await handleApp(
      new Request("https://local.test/api/users/SAM/weights", {
        headers: healthAuth,
      }),
      env,
    );
    assert.equal(ambiguous.status, 409);
    assert.match(
      ((await ambiguous.json()) as { error: string }).error,
      /ambiguous short name/,
    );
    assert.equal(
      (
        await handleApp(
          new Request("https://local.test/api/users/SAM/health-sync/next", {
            headers: healthAuth,
          }),
          env,
        )
      ).status,
      409,
    );
    assert.equal(
      (
        await handleApp(
          new Request("https://local.test/api/users/1/weights", {
            headers: healthAuth,
          }),
          env,
        )
      ).status,
      200,
    );
  } finally {
    store.close();
    rmSync(directory, { recursive: true, force: true });
  }
});

test("reviewed capture can stage users and fixtures without sending a roster", async () => {
  const directory = mkdtempSync(join(tmpdir(), "yow-capture-test-"));
  const store = new LocalSqlite(join(directory, "capture.sqlite3"));
  const env: AppEnv = {
    DB: store.asD1(),
    YOW_BOOTSTRAP_TOKEN: "test-bootstrap-token-123456",
  };
  let cookie = "";
  let csrf = "";
  const get = async (path: string) =>
    handleApp(
      new Request(`https://local.test${path}`, {
        headers: cookie ? { Cookie: cookie } : {},
      }),
      env,
    );
  const send = async (path: string, form: FormData | URLSearchParams) =>
    handleApp(
      new Request(`https://local.test${path}`, {
        method: "POST",
        headers: { Cookie: cookie },
        body: form,
      }),
      env,
    );
  const post = (path: string, values: Record<string, string>) =>
    send(path, new URLSearchParams({ _csrf: csrf, ...values }));
  try {
    const setup = await get("/setup");
    cookie = setup.headers.get("set-cookie")!.split(";")[0];
    csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(await setup.text())![1];
    const created = await post("/setup", {
      bootstrap_token: "test-bootstrap-token-123456",
      password: "admin-password",
      confirm: "admin-password",
    });
    cookie = created.headers.get("set-cookie")!.split(";")[0];
    csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(
      await (await get("/")).text(),
    )![1];
    await post("/scales", {
      label: "Bathroom",
      mac: "24:E4:2F:12:34:56",
      secret: "secret",
    });
    assert.equal(
      (
        await handleApp(
          new Request("https://local.test/once", {
            method: "POST",
            body: new URLSearchParams({ action: "get" }),
          }),
          env,
        )
      ).status,
      200,
    );
    const capture = {
      format: "WBS06-Withings-readonly-baseline-v1",
      mac: "24:E4:2F:12:34:56",
      ctp: { goff: 3600, dst: 0, ngoff: 3600 },
      ind: { fm: 3, ws: 0, tmp: 11, w: 1 },
      sp: {
        users: [
          {
            id: 17,
            fn: "Sam",
            sn: "SAM",
            ht: 1.81,
            agt: 40,
            sx: 0,
            wt: 73,
            cr: 123,
            fm: 0,
            att: 0,
            cs: "",
            ptf: 0,
            bd: 0,
          },
        ],
      },
      screen_response: { status: 0, body: { device: [], user: [] } },
      summary_response: { status: 0, body: [] },
    };
    let calls = 0;
    env.captureWithings = async (scale) => {
      calls++;
      assert.equal(scale.mac, "24E42F123456");
      return JSON.stringify(capture);
    };
    assert.match(
      await (await get("/users")).text(),
      /Fetch From Withings/,
    );
    const fetched = await post("/users/fetch-withings", {
      scale_id: "1",
      plaintext_http_ack: "1",
    });
    assert.equal(fetched.status, 303);
    assert.equal(calls, 1);
    assert.match(fetched.headers.get("location") ?? "", /preview_scale=1/);
    const upload = new FormData();
    upload.set("_csrf", csrf);
    upload.set(
      "capture",
      new File([JSON.stringify(capture)], "capture.json", {
        type: "application/json",
      }),
    );
    const staged = await send("/scales/1/capture", upload);
    assert.equal(staged.status, 303);
    const preview = await get("/users?preview_scale=1");
    const page = await preview.text();
    assert.match(page, /Import Users From/);
    assert.match(page, /Device settings are ready/);
    const digest = /name="capture_digest" value="([a-f0-9]+)"/.exec(page)![1];
    const imported = await post("/users/import-withings/confirm", {
      scale_id: "1",
      capture_digest: digest,
      user_ids: "17",
    });
    assert.equal(imported.status, 303);
    assert.equal(
      (
        await store
          .asD1()
          .prepare("SELECT COUNT(*) AS count FROM users")
          .first<{ count: number }>()
      )?.count,
      1,
    );
    const before = await store
      .asD1()
      .prepare("SELECT roster_enabled,settings_ready FROM scales WHERE id=1")
      .first<{ roster_enabled: number; settings_ready: number }>();
    assert.equal(before?.roster_enabled, 0);
    assert.equal(before?.settings_ready, 1);
    const combined = await post("/users/import-withings/confirm", {
      scale_id: "1",
      capture_digest: digest,
      import_scale_settings: "1",
      time_zone: "Europe/Berlin",
    });
    assert.equal(combined.status, 303);
    const configured = await store
      .asD1()
      .prepare(
        "SELECT settings_ready,screen_response,summary_response,time_zone,roster_enabled FROM scales WHERE id=1",
      )
      .first<{
        settings_ready: number;
        screen_response: string;
        summary_response: string;
        time_zone: string;
        roster_enabled: number;
      }>();
    assert.equal(configured?.settings_ready, 1);
    assert.ok(configured?.screen_response && configured?.summary_response);
    assert.equal(configured?.time_zone, null);
    assert.equal(configured?.roster_enabled, 0);
    assert.equal(
      (
        await handleApp(
          new Request("https://local.test/once", {
            method: "POST",
            body: new URLSearchParams({ action: "get" }),
          }),
          env,
        )
      ).status,
      200,
    );
    const bleRecord = {
      format: "YOW-BLE-device-v1",
      model: "WBS06",
      name: "Body",
      mac: "24:E4:2F:12:34:57",
      session_secret: "0123456789abcdef",
      hardware_version: 0xffffff,
      probe_identifier: "test-scale",
      bootloader_version: 4,
      firmware_version: 126,
      rescue_version: 0xffffffff,
      wifi_ssid: "Home",
      owner_host: "example.com",
      owner_transport: "https",
      captured_at: Math.floor(Date.now() / 1000),
    };
    const bleUpload = new FormData();
    bleUpload.set("_csrf", csrf);
    bleUpload.set(
      "record",
      new File([JSON.stringify(bleRecord)], "scale.yow-device.json", {
        type: "application/json",
      }),
    );
    const enrolled = await send("/scales/import-ble", bleUpload);
    assert.equal(enrolled.status, 303);
    assert.match(
      enrolled.headers.get("location") ?? "",
      /^\/scales\?notice=.*#scale-2$/,
    );
    const offer = await (await get("/users?import_scale=2")).text();
    assert.match(offer, /id="import-users-dialog" data-auto-open/);
    assert.match(offer, /<option value="2" selected>/);
    const classicRecord = {
      ...bleRecord,
      format: "YOW-Classic-device-v1",
      model: "WBS03",
      name: "Withings WS30",
      mac: "00:11:22:33:44:66",
      hardware_version: 1,
      bootloader_version: 15,
      firmware_version: 101,
      owner_host: "scales.example.com",
      owner_transport: "http",
    };
    const classicUpload = new FormData();
    classicUpload.set("_csrf", csrf);
    classicUpload.set(
      "record",
      new File([JSON.stringify(classicRecord)], "ws30.yow-device.json", {
        type: "application/json",
      }),
    );
    const classicEnrolled = await send("/scales/import-ble", classicUpload);
    assert.equal(classicEnrolled.status, 303);
    assert.match(
      classicEnrolled.headers.get("location") ?? "",
      /^\/scales\?notice=.*#scale-3$/,
    );
    const classicScale = await store
      .asD1()
      .prepare(
        "SELECT model,mac,ble_owner_host,ble_owner_transport FROM scales WHERE id=3",
      )
      .first<{
        model: string;
        mac: string;
        ble_owner_host: string;
        ble_owner_transport: string;
      }>();
    assert.deepEqual(classicScale && { ...classicScale }, {
      model: "WBS03",
      mac: "001122334466",
      ble_owner_host: "scales.example.com",
      ble_owner_transport: "http",
    });
    assert.equal(
      (
        await post("/scales/3", {
          purpose: "config",
          label: "Classic Scale",
          time_zone: "Europe/Berlin",
        })
      ).status,
      303,
    );
    const classicSettings = await store
      .asD1()
      .prepare(
        "SELECT label,time_zone,settings_ready,roster_enabled FROM scales WHERE id=3",
      )
      .first();
    assert.deepEqual(
      { ...classicSettings },
      {
        label: "Classic Scale",
        time_zone: "Europe/Berlin",
        settings_ready: 0,
        roster_enabled: 0,
      },
    );
    const devicePage = await (await get("/scales")).text();
    const classicCard = devicePage.slice(
      devicePage.indexOf('id="scale-3"'),
      devicePage.indexOf("</section>", devicePage.indexOf('id="scale-3"')) + 10,
    );
    assert.match(classicCard, /class="badge">Ready</);
    const classicModal = devicePage
      .split('id="edit-device-3"')[1]
      .split("</dialog>")[0];
    assert.doesNotMatch(
      classicModal,
      /name="feature_mask"|name="roster_enabled"/,
    );
    assert.equal((await post("/users/17/delete", {})).status, 303);
    assert.equal(
      (
        await store
          .asD1()
          .prepare("SELECT COUNT(*) AS count FROM users")
          .first<{ count: number }>()
      )?.count,
      0,
    );
  } finally {
    store.close();
    rmSync(directory, { recursive: true, force: true });
  }
});

test("portable PBKDF2 hash logs in and admin rotation invalidates other sessions", async () => {
  const directory = mkdtempSync(join(tmpdir(), "yow-password-test-"));
  const store = new LocalSqlite(join(directory, "password.sqlite3"));
  const env: AppEnv = { DB: store.asD1() };
  const oldHash =
    "pbkdf2_sha256$600000$000102030405060708090a0b0c0d0e0f$" +
    "5e470be3aac01b9df58840e2db41d217a2e240bc493fcb1aa0f4bbdc30c660f7";
  await store
    .asD1()
    .batch([
      store
        .asD1()
        .prepare("INSERT INTO settings(key,value) VALUES('admin_password',?)")
        .bind(oldHash),
      store
        .asD1()
        .prepare("INSERT INTO settings(key,value) VALUES('auth_version','3')"),
    ]);
  async function login(): Promise<{ cookie: string; csrf: string }> {
    const page = await handleApp(new Request("https://local.test/login"), env);
    const cookie = page.headers.get("set-cookie")!.split(";")[0];
    const csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(await page.text())![1];
    const signed = await handleApp(
      new Request("https://local.test/login", {
        method: "POST",
        headers: { Cookie: cookie },
        body: new URLSearchParams({
          _csrf: csrf,
          password: "admin-password-123",
        }),
      }),
      env,
    );
    assert.equal(signed.status, 303);
    return { cookie: signed.headers.get("set-cookie")!.split(";")[0], csrf };
  }
  try {
    const first = await login(),
      second = await login();
    const page = await handleApp(
      new Request("https://local.test/settings", {
        headers: { Cookie: first.cookie },
      }),
      env,
    );
    const csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(await page.text())![1];
    const changed = await handleApp(
      new Request("https://local.test/settings", {
        method: "POST",
        headers: { Cookie: first.cookie },
        body: new URLSearchParams({
          _csrf: csrf,
          purpose: "admin_password",
          current: "admin-password-123",
          new: "new-password-123",
          confirm: "new-password-123",
        }),
      }),
      env,
    );
    assert.equal(changed.status, 303);
    const rotated = await store
      .asD1()
      .prepare("SELECT value FROM settings WHERE key='admin_password'")
      .first<{ value: string }>();
    assert.match(rotated?.value ?? "", /^pbkdf2_sha256\$100000\$/);
    assert.equal(
      (
        await handleApp(
          new Request("https://local.test/", {
            headers: { Cookie: first.cookie },
          }),
          env,
        )
      ).status,
      200,
    );
    const stale = await handleApp(
      new Request("https://local.test/", {
        headers: { Cookie: second.cookie },
      }),
      env,
    );
    assert.equal(stale.status, 303);
    assert.equal(stale.headers.get("location"), "/login");
  } finally {
    store.close();
    rmSync(directory, { recursive: true, force: true });
  }
});
