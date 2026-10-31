import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LocalSqlite } from "../sqlite.ts";
import { handleApp, type AppEnv } from "../app.ts";
import { exportBackup, stageBackup, commitBackup } from "../backup.ts";

// Synthetic identities and sensor values, retaining the observed WBS13 wire shape.
const MAC = "02:00:00:00:00:13",
  SECRET = "0123456789abcdef";
async function harness() {
  const dir = mkdtempSync(join(tmpdir(), "yow-metrics-"));
  const store = new LocalSqlite(join(dir, "source.db")),
    db = store.asD1();
  let cookie = "",
    csrf = "",
    vendorCalls = 0;
  const env: AppEnv = {
    DB: db,
    ALLOW_HTTP_SCALE: true,
    captureWithings: async () => {
      vendorCalls++;
      throw new Error("Must not fetch WBS13 vendor profile");
    },
  };
  const web = async (
    path: string,
    body?: URLSearchParams | Record<string, unknown>,
  ) => {
    const headers: Record<string, string> = {
      Cookie: cookie,
      Origin: "http://localhost",
    };
    if (body instanceof URLSearchParams) {
      body.set("_csrf", csrf);
      headers["Content-Type"] = "application/x-www-form-urlencoded";
    } else if (body) {
      headers["Content-Type"] = "application/json";
      headers["X-CSRF-Token"] = csrf;
    }
    const r = await handleApp(
      new Request(`http://localhost${path}`, {
        method: body ? "POST" : "GET",
        headers,
        body:
          body instanceof URLSearchParams
            ? body.toString()
            : body
              ? JSON.stringify(body)
              : undefined,
      }),
      env,
    );
    if (r.headers.has("Set-Cookie"))
      cookie = r.headers.get("Set-Cookie")!.split(";")[0];
    return r;
  };
  csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(
    await (await web("/setup")).text(),
  )![1];
  assert.equal(
    (
      await web(
        "/setup",
        new URLSearchParams({
          password: "test-password",
          confirm: "test-password",
        }),
      )
    ).status,
    303,
  );
  csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(
    await (await web("/")).text(),
  )![1];
  await db
    .prepare(
      "INSERT INTO users(id,name,short_name,height_cm,age_years,sex,reference_weight_kg,created_at) VALUES(17,'Alex','ALX',180,40,0,80,1700000000),(18,'Sam','SAM',170,35,1,70,1700000000)",
    )
    .run();
  const post = (path: string, fields: Record<string, string>) =>
    handleApp(
      new Request(`http://scales.test${path}`, {
        method: "POST",
        body: new URLSearchParams(fields),
      }),
      env,
    );
  const open = async () => {
    const challenge = (await (
      await post("/once", { action: "get" })
    ).json()) as any;
    return post("/session?appname=WBS13&appliver=100", {
      action: "new",
      auth: MAC,
      hashmethod: "sha256",
      hash: createHash("sha256")
        .update(`${MAC}:${SECRET}:${challenge.body.once}`)
        .digest("hex"),
      currentfw: "100",
    });
  };
  const device = {
    format: "YOW-BLE-device-v1",
    model: "WBS13",
    name: "Body Smart",
    mac: MAC,
    session_secret: SECRET,
    hardware_version: 0xffffff,
    bootloader_version: 2,
    firmware_version: 100,
    rescue_version: 0xffffff,
    captured_at: Math.floor(Date.now() / 1000),
  };
  const enrollment = await web("/api/scales/enroll", {
    device,
    timeZone: "Europe/Berlin",
  });
  assert.equal(enrollment.status, 200, await enrollment.clone().text());
  const info = (await enrollment.json()) as any;
  assert.equal(info.localRoster, true);
  assert.equal(vendorCalls, 0);
  assert.equal((await open()).status, 503); // Never clear an unconfigured scale's existing roster.
  const settings = new URLSearchParams({
    purpose: "device_config",
    label: "Test Body Smart",
    time_zone: "Europe/Berlin",
    user_ids: "17",
  });
  assert.equal((await web(`/scales/${info.scaleId}`, settings)).status, 303);
  const api = (path: string, method = "GET") =>
    handleApp(
      new Request(`https://app.test${path}`, {
        method,
        headers: { Authorization: `Basic ${btoa("reader:test-password")}` },
      }),
      env,
    );
  return {
    dir,
    store,
    db,
    env,
    web,
    post,
    open,
    api,
    scaleId: info.scaleId,
    cleanup: () => {
      store.close();
      rmSync(dir, { recursive: true, force: true });
    },
  };
}

test("WBS13 authenticates, receives its local roster every session and stores mixed measurement groups atomically", async () => {
  const h = await harness();
  try {
    for (let repeat = 0; repeat < 2; repeat++) {
      const response = await h.open();
      assert.equal(response.status, 200);
      const session = ((await response.json()) as any).body;
      assert.equal(session.sp.users[0].id, 17);
      assert.equal(session.sp.users[0].cs, "2,1,3");
      assert.equal(session.sp.users[0].wt, 80);
      assert.deepEqual(session.ind, { stp: 0, fm: 0, ws: 0 });
    }
    const session = ((await (await h.open()).json()) as any).body.sessionid;
    const common = { sessionid: session };
    for (const [path, action, extra, body] of [
      ["/v2/summary", "getforscale", {}, []],
      ["/v2/measure", "getlastupdate", { objects: "devices" }, { devices: [] }],
      [
        "/v2/feature",
        "getbydevice",
        {},
        { device_features: [], user_features: [] },
      ],
      ["/v2/screen", "getcontentbydeviceid", {}, { user_screens: [] }],
    ] as const) {
      const r = await h.post(path, { ...common, action, ...extra });
      assert.equal(r.status, 200);
      assert.deepEqual(((await r.json()) as any).body, body);
    }
    const screen = await h.post("/v2/screen", {
      ...common,
      action: "getbydeviceid",
    });
    assert.deepEqual(
      ((await screen.json()) as any).body.user[0].screens.map(
        (s: any) => s.embid,
      ),
      [2, 1, 3],
    );
    const timestamp = Math.floor(Date.now() / 1000) - 60;
    const groups = [
      {
        meastime: timestamp,
        algo: 218300672,
        source_note: { sensor: "synthetic" },
        measures: [
          { value: 80000, type: 1, unit: -3 },
          { value: 2000, type: 8, unit: -2, position: 6 },
          { value: 6000, type: 5, unit: -2, position: 6 },
          { value: 4000, type: 77, unit: -2, position: 6 },
          { value: 300, type: 88, unit: -2, position: 6 },
          { value: 5700, type: 76, unit: -2, position: 6 },
          { value: 35, type: 170, unit: -1, position: 6 },
          { value: 1800, type: 226, unit: 0, position: 6 },
          { value: 42, type: 227, unit: 0, position: 6 },
          { value: 500, type: 189, unit: 0, position: 6, quality: "test" },
        ],
      },
      { meastime: timestamp, measures: [{ value: 72, type: 11, unit: 0 }] },
    ];
    const fields = {
      ...common,
      action: "batchstore",
      macaddress: MAC,
      userid: "17",
      devtype: "1",
      category: "1",
      attribstatus: "0",
      measuregrps: JSON.stringify({ measuregrps: groups }),
    };
    for (let i = 0; i < 2; i++)
      assert.equal((await h.post("/measure", fields)).status, 200);
    const saved = (
      await h.db.prepare("SELECT * FROM readings ORDER BY id").all<any>()
    ).results;
    assert.equal(saved.length, 2);
    assert.equal(saved[1].weight_value, null);
    assert.equal(saved[1].weight_unit, null);
    assert.deepEqual(JSON.parse(saved[0].group_json), groups[0]);
    assert.equal(saved[0].attempts, 2);
    assert.equal(JSON.parse(saved[0].measures_json).at(-1).quality, "test");
    const all = (await (await h.api("/api/users/ALX/readings")).json()) as any;
    assert.equal(all.readings.length, 2);
    assert.equal(all.readings[0].metrics.heart_rate_bpm, "72");
    assert.equal(all.readings[0].weight_kg, null);
    assert.equal(all.readings[1].metrics.fat_mass_kg, "20.00");
    assert.equal(all.readings[1].group.algo, 218300672);
    assert.equal(all.readings[1].measures.at(-1).type, 189);
    assert.equal(
      all.available_metrics.some((m: any) => m.type === 189),
      false,
    );
    const first = (await (
      await h.api("/api/users/17/readings?limit=1")
    ).json()) as any;
    const second = (await (
      await h.api(`/api/users/17/readings?limit=1&cursor=${first.next_cursor}`)
    ).json()) as any;
    assert.equal(first.readings[0].id, saved[1].id);
    assert.equal(second.readings[0].id, saved[0].id);
    assert.equal(second.next_cursor, null);
    const weights = (await (
      await h.api("/api/users/17/weights")
    ).json()) as any;
    assert.equal(weights.readings.length, 1);
    assert.equal(weights.readings[0].weight_kg, "80.000");
    let health = (await (
      await h.api("/api/users/17/health-sync/next")
    ).json()) as any;
    assert.equal(health.reading.id, saved[0].id);
    assert.equal(
      (
        await h.api(
          `/api/users/17/health-sync/ack?reading_id=${saved[1].id}`,
          "POST",
        )
      ).status,
      404,
    );
    assert.equal(
      (
        await h.api(
          `/api/users/17/health-sync/ack?reading_id=${saved[0].id}`,
          "POST",
        )
      ).status,
      200,
    );
    health = (await (
      await h.api("/api/users/17/health-sync/next")
    ).json()) as any;
    assert.equal(health.reading, null);
    const html = await (await h.web("/")).text();
    assert.match(html, /80\.00 kg/);
    assert.match(html, />Heart Rate</);
    assert.doesNotMatch(html.split('name="metric_18"')[1] ?? "", /Heart Rate/); // Sam has no new metric.
    const heart = await (await h.web("/?metric_17=11")).text();
    assert.match(heart, /72 bpm/);
    assert.doesNotMatch(heart, /0\.00 kg/);
    assert.match(await (await h.web("/readings?metric=8")).text(), /20\.00 kg/);
    // More recent weight-only rows must not hide previously received metrics.
    for (let i = 0; i < 12; i++)
      await h.post("/measure", {
        ...fields,
        measuregrps: JSON.stringify({
          measuregrps: [
            {
              meastime: timestamp + i + 1,
              algo: 0,
              measures: [{ value: 81000 + i, type: 1, unit: -3 }],
            },
          ],
        }),
      });
    assert.match(await (await h.web("/?metric_17=11")).text(), /72 bpm/);
    assert.match(await (await h.web("/readings")).text(), />Heart Rate</);
    assert.doesNotMatch(
      await (await h.web("/users/18/readings")).text(),
      />Heart Rate</,
    );
    assert.equal(
      (await h.post("/session", { ...common, action: "delete" })).status,
      200,
    );
    assert.equal((await h.post("/measure", fields)).status, 403);
    // Raw groups and nullable weights survive portable backup, including receipts.
    const backup = await exportBackup(h.db);
    for (const bad of [
      "broken JSON",
      "{}",
      '[{"type":11,"value":72,"unit":100}]',
    ]) {
      const invalid = structuredClone(backup);
      invalid.sections.readings[1].measures_json = bad;
      await assert.rejects(stageBackup(h.db, JSON.stringify(invalid), "admin"));
    }
    const invalidGroup = structuredClone(backup);
    invalidGroup.sections.readings[0].group_json =
      '{"meastime":0,"measures":[]}';
    await assert.rejects(
      stageBackup(h.db, JSON.stringify(invalidGroup), "admin"),
      /Invalid stored measurement group/,
    );
    const restored = new LocalSqlite(join(h.dir, "restored.db"));
    try {
      const stage = await stageBackup(
        restored.asD1(),
        JSON.stringify(backup),
        "admin",
      );
      await commitBackup(
        restored.asD1(),
        stage.id,
        stage.digest,
        "admin",
        "replace",
        false,
      );
      assert.equal(
        (
          await restored
            .prepare("SELECT group_json FROM readings WHERE id=?")
            .bind(saved[0].id)
            .first<any>()
        ).group_json,
        saved[0].group_json,
      );
      assert.equal(
        (
          await restored
            .prepare("SELECT weight_value FROM readings WHERE id=?")
            .bind(saved[1].id)
            .first<any>()
        ).weight_value,
        null,
      );
      assert.equal(
        (
          await restored
            .prepare("SELECT COUNT(*) AS n FROM health_sync_receipts")
            .first<any>()
        ).n,
        1,
      );
    } finally {
      restored.close();
    }
  } finally {
    h.cleanup();
  }
});

test("weight-only retries retain the legacy digest; metadata cannot overwrite group identity and failed batches are not acknowledged", async () => {
  const h = await harness();
  try {
    const sid = ((await (await h.open()).json()) as any).body.sessionid;
    const base = {
      action: "batchstore",
      sessionid: sid,
      macaddress: MAC,
      userid: "17",
      devtype: "1",
      category: "1",
    };
    const group = {
      meastime: Math.floor(Date.now() / 1000) - 60,
      measures: [{ value: 80000, type: 1, unit: -3 }],
    };
    const send = (groups: unknown[]) =>
      h.post("/measure", {
        ...base,
        measuregrps: JSON.stringify({ measuregrps: groups }),
      });
    assert.equal((await send([group])).status, 200);
    assert.equal((await send([{ ...group, algo: 0 }])).status, 200);
    assert.equal(
      (await h.db.prepare("SELECT COUNT(*) AS n FROM readings").first<any>())!
        .n,
      1,
    );
    const metadata = {
      mac: "fake",
      index: 0,
      candidate_ids: [],
      note: "same metadata",
    };
    assert.equal(
      (
        await send([
          { ...group, ...metadata },
          { ...group, ...metadata },
        ])
      ).status,
      200,
    );
    assert.equal(
      (await h.db.prepare("SELECT COUNT(*) AS n FROM readings").first<any>())!
        .n,
      3,
    );
    const before = (await h.db
      .prepare("SELECT COUNT(*) AS n FROM readings")
      .first<any>())!.n;
    assert.equal(
      (
        await send([
          group,
          {
            meastime: group.meastime,
            measures: [{ type: 11, value: 72, unit: 100 }],
          },
        ])
      ).status,
      400,
    );
    assert.equal(
      (await h.db.prepare("SELECT COUNT(*) AS n FROM readings").first<any>())!
        .n,
      before,
    );
    const db = h.env.DB;
    h.env.DB = {
      prepare: db.prepare.bind(db),
      batch: async () => {
        throw new Error("disk failure");
      },
    } as unknown as D1Database;
    await assert.rejects(
      send([{ ...group, meastime: group.meastime + 20 }]),
      /disk failure/,
    );
  } finally {
    h.cleanup();
  }
});
