import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LocalSqlite } from "../sqlite.ts";
import { handleApp, type AppEnv } from "../app.ts";
import { screenIds } from "../scale_api.ts";

// Synthetic Body Cardio identity; locally administered MAC.
const MAC = "02:00:00:00:00:04",
  SECRET = "0123456789abcdef";

function capture(users: Record<string, unknown>[]) {
  return JSON.stringify({
    format: "WBS06-Withings-readonly-baseline-v1",
    mac: MAC,
    ctp: { goff: 3600, dst: 0, ngoff: 3600 },
    ind: { fm: 3, ws: 0, tmp: 11, w: 1 },
    sp: { users },
  });
}
const user = (extra: Record<string, unknown>) => ({
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
  ptf: 0,
  bd: 0,
  ...extra,
});

async function harness(profile: () => string) {
  const dir = mkdtempSync(join(tmpdir(), "yow-wbs04-"));
  const store = new LocalSqlite(join(dir, "wbs04.db")),
    db = store.asD1();
  const env: AppEnv = {
    DB: db,
    ALLOW_HTTP_SCALE: true,
    captureWithings: async () => profile(),
  };
  let cookie = "",
    csrf = "";
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
  await web(
    "/setup",
    new URLSearchParams({
      password: "test-password",
      confirm: "test-password",
    }),
  );
  csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(
    await (await web("/")).text(),
  )![1];
  const post = (path: string, fields: Record<string, string>) =>
    handleApp(
      new Request(`http://scales.test${path}`, {
        method: "POST",
        body: new URLSearchParams(fields),
      }),
      env,
    );
  const enroll = async () =>
    (await (
      await web("/api/scales/enroll", {
        device: {
          format: "YOW-BLE-device-v1",
          model: "WBS04",
          name: "Body Cardio",
          mac: MAC,
          session_secret: SECRET,
          hardware_version: 0xffffff,
          bootloader_version: 12,
          firmware_version: 100,
          rescue_version: 0xffffff,
          captured_at: Math.floor(Date.now() / 1000),
        },
        timeZone: "Europe/Berlin",
      })
    ).json()) as any;
  const screens = async () => {
    const challenge = (await (
      await post("/once", { action: "get" })
    ).json()) as any;
    const opened = await post("/session?appname=WBS04&appliver=100", {
      action: "new",
      auth: MAC,
      hashmethod: "sha256",
      hash: createHash("sha256")
        .update(`${MAC}:${SECRET}:${challenge.body.once}`)
        .digest("hex"),
      currentfw: "100",
    });
    assert.equal(opened.status, 200, await opened.clone().text());
    const sessionid = ((await opened.json()) as any).body.sessionid;
    const r = await post("/v2/screen", { sessionid, action: "getbydeviceid" });
    assert.equal(r.status, 200, await r.clone().text());
    return ((await r.json()) as any).body.user.map((u: any) =>
      u.screens.map((s: any) => s.embid),
    );
  };
  return {
    db,
    enroll,
    screens,
    cleanup: () => {
      store.close();
      rmSync(dir, { recursive: true, force: true });
    },
  };
}

test("screenIds parses roster cs and rejects missing or malformed values", () => {
  assert.deepEqual(screenIds("11,3,12"), [11, 3, 12]);
  assert.deepEqual(screenIds(""), []);
  for (const bad of [undefined, null, 2, "2,", ",2", "2;1", "a", "1,,2"])
    assert.equal(screenIds(bad), null, String(bad));
});

test("WBS04 enrollment rejects a capture whose user lacks screen IDs (cs)", async () => {
  const h = await harness(() => capture([user({})]));
  try {
    const info = await h.enroll();
    assert.equal(info.migrationIncomplete, true);
    const scale = await h.db
      .prepare("SELECT settings_ready,roster_snapshot FROM scales")
      .first<{ settings_ready: number; roster_snapshot: string | null }>();
    assert.equal(scale?.settings_ready, 0);
    assert.equal(scale?.roster_snapshot, null);
    const staged = await h.db
      .prepare("SELECT COUNT(*) AS count FROM reviewed_captures")
      .first<{ count: number }>();
    assert.equal(staged?.count, 0);
  } finally {
    h.cleanup();
  }
});

test("WBS04 screens follow cs and fall back to weight when a baseline lacks it", async () => {
  const h = await harness(() => capture([user({ cs: "11,3,12,6,1" })]));
  try {
    const info = await h.enroll();
    assert.equal(info.migrationIncomplete, undefined, JSON.stringify(info));
    assert.deepEqual(await h.screens(), [[11, 3, 12, 6, 1]]);
    const setCs = async (value: unknown) => {
      const snapshot = JSON.parse(
        (await h.db
          .prepare("SELECT roster_snapshot FROM scales")
          .first<{ roster_snapshot: string }>())!.roster_snapshot,
      );
      if (value === undefined) delete snapshot[0].cs;
      else snapshot[0].cs = value;
      await h.db
        .prepare("UPDATE scales SET roster_snapshot=?")
        .bind(JSON.stringify(snapshot))
        .run();
    };
    // An explicit empty selection (the user turned every screen off) is kept,
    // not replaced by the weight screen.
    await setCs("");
    assert.deepEqual(await h.screens(), [[]]);
    // A baseline from an older import, backup or manual edit without `cs`
    // must not break every screen request: it falls back to the weight screen.
    await setCs(undefined);
    assert.deepEqual(await h.screens(), [[2]]);
  } finally {
    h.cleanup();
  }
});
