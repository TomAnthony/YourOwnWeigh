/** Offline vendor compatibility and WS-30 import regressions using a sanitized
 * WS-30 upstream response; WS50 replay does not establish live compatibility.
 * Optional YOW_WITHINGS_TEST_CAPTURE selects a private baseline for a local check.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { captureWithings } from "../withings_capture.ts";
import { handleApp, type AppEnv } from "../app.ts";
import { LocalSqlite } from "../sqlite.ts";

const MAC = "02:00:00:00:30:01";
const SECRET = "0123456789abcdef";
const baseline = JSON.parse(readFileSync(process.env.YOW_WITHINGS_TEST_CAPTURE ??
  new URL("../../../contracts/withings/ws30-baseline.sanitized.json", import.meta.url), "utf8"));
// A private baseline may be tested without copying its real identity into the DB.
baseline.mac = MAC;

for (const [model, firmware] of [["WBS03", 102], ["WS50", 1023]] as const) {
test(`${model} vendor capture keeps compatibility authentication independent of owner firmware`, async (t) => {
  const calls: string[] = [];
  t.mock.method(globalThis, "fetch", async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input));
    assert.equal(url.origin, "https://scalews.withings.net");
    assert.deepEqual(Object.fromEntries(url.searchParams), {
      appliver: "1181", appname: "WBS06", apppfm: "device",
    });
    const path = url.pathname.slice(1);
    calls.push(path);
    const form = new URLSearchParams(String(init?.body));
    if (path === "once") return Response.json({ status: 0, body: { once: "synthetic-challenge" } });
    if (path === "session") {
      assert.equal(form.get("auth"), MAC);
      assert.equal(form.get("hashmethod"), "sha256");
      assert.equal(form.get("hash"), createHash("sha256").update(`${MAC}:${SECRET}:synthetic-challenge`).digest("hex"));
      // Vendor compatibility parameters are independent of the model's
      // owner-server authentication and its observed running firmware.
      assert.equal(form.get("currentfw"), "1181");
      assert.equal(form.get("mfgid"), "0");
      assert.equal(form.get("feature_mask"), "0");
      return Response.json({ status: 0, body: { sessionid: "synthetic-session", ctp: baseline.ctp,
        ind: baseline.ind, sp: baseline.sp, syp: { utc: 1, blc: "https://example.invalid/unused.bin" } } });
    }
    assert.equal(form.get("sessionid"), "synthetic-session");
    if (path === "v2/screen") return Response.json(baseline.screen_response);
    if (path === "v2/summary") return Response.json(baseline.summary_response);
    throw new Error(`Unexpected upstream call: ${path}`);
  });
  const raw = await captureWithings({ model, mac: MAC, secret: SECRET, ble_firmware_version: firmware });
  assert.deepEqual(calls, ["once", "session", "v2/screen", "v2/summary"]);
  const capture = JSON.parse(raw);
  assert.deepEqual(capture, baseline);
  assert.equal(capture.ind.fm, 0);
  assert.deepEqual(capture.screen_response.body.device, []);
  assert.deepEqual(capture.sp.users.map((user: Record<string, unknown>) => user.cs), baseline.sp.users.map((user: Record<string, unknown>) => user.cs));
  assert.equal(capture.sessionid, undefined);
  assert.equal(capture.syp, undefined);
  assert.equal(raw.includes(SECRET), false);
});
}

test("WS-30 captured users pass the current importer and leave the minimal v101 sync path intact", async () => {
  const directory = mkdtempSync(join(tmpdir(), "yow-ws30-import-"));
  const store = new LocalSqlite(join(directory, "test.sqlite3"));
  const db = store.asD1();
  let fetchCount = 0;
  const env: AppEnv = { DB: db, ALLOW_HTTP_SCALE: true, YOW_BOOTSTRAP_TOKEN: "synthetic-bootstrap-token",
    captureWithings: async scale => {
      fetchCount++;
      assert.equal(scale.model, "WBS03");
      assert.equal(scale.mac, MAC.replaceAll(":", "").toUpperCase());
      return JSON.stringify(baseline);
    } };
  let cookie = "", csrf = "";
  const get = (path: string) => handleApp(new Request(`https://local.test${path}`,
    { headers: cookie ? { Cookie: cookie } : {} }), env);
  const post = (path: string, fields: Record<string, string>) => handleApp(new Request(`https://local.test${path}`,
    { method: "POST", headers: { Cookie: cookie }, body: new URLSearchParams([...Object.entries({ _csrf: csrf, ...fields }), ...(path.endsWith("/confirm") ? baseline.sp.users.map((u: {id:number}) => ["user_ids",String(u.id)]) : [])]) }), env);
  const scalePost = (path: string, fields: Record<string, string>) => handleApp(new Request(`http://scales.test${path}`,
    { method: "POST", body: new URLSearchParams(fields) }), env);
  try {
    const setup = await get("/setup");
    cookie = setup.headers.get("set-cookie")!.split(";")[0];
    csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(await setup.text())![1];
    const created = await post("/setup", { bootstrap_token: env.YOW_BOOTSTRAP_TOKEN!,
      password: "synthetic-password", confirm: "synthetic-password" });
    assert.equal(created.status, 303);
    cookie = created.headers.get("set-cookie")!.split(";")[0];
    csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(await (await get("/")).text())![1];
    await db.prepare("INSERT INTO scales(id,label,model,mac,secret) VALUES(1,'Synthetic WS-30','WBS03',?,?)")
      .bind(MAC.replaceAll(":", "").toUpperCase(), SECRET).run();
    const config = () => db.prepare("SELECT settings_ready,screen_response,summary_response,weather_response," +
      "goff,dst,ngoff,feature_mask,beta_ws,temp_code,weight_code,time_zone,roster_enabled FROM scales WHERE id=1").first();
    const before = await config();
    const fetched = await post("/users/fetch-withings", { scale_id: "1" });
    assert.equal(fetched.status, 303);
    assert.match(fetched.headers.get("location") ?? "", /preview_scale=1/);
    assert.equal(fetchCount, 1);
    const page = await (await get("/users?preview_scale=1")).text();
    assert.match(page, /Import Users From/);
    const digest = /name="capture_digest" value="([a-f0-9]+)"/.exec(page)?.[1];
    assert.ok(digest, "Real response shape must pass capture normalization and produce a preview");
    const imported = await post("/users/import-withings/confirm", { scale_id: "1", capture_digest: digest });
    assert.equal(imported.status, 303);
    const redirect = new URL(imported.headers.get("location")!, "https://local.test");
    assert.equal(redirect.pathname, "/users");
    assert.match(redirect.searchParams.get("notice") ?? "", /Selected users imported/);
    const users = (await db.prepare("SELECT id,height_cm,reference_weight_kg FROM users ORDER BY id").all()).results;
    assert.equal(users.length, baseline.sp.users.length);
    for (const user of users) {
      const source = baseline.sp.users.find((item: Record<string, unknown>) => item.id === user.id);
      assert.ok(source);
      assert.equal(user.height_cm, Math.round(source.ht * 100));
      assert.equal(user.reference_weight_kg, source.wt);
    }
    assert.equal((await db.prepare("SELECT COUNT(*) AS count FROM scale_users WHERE scale_id=1").first())?.count, users.length);
    assert.deepEqual(await config(), before, "Users-only import must not change model settings/display state");
    const saved = await db.prepare("SELECT roster_snapshot FROM scales WHERE id=1").first<{ roster_snapshot: string }>();
    assert.deepEqual(JSON.parse(saved!.roster_snapshot), baseline.sp.users);

    const once = await scalePost("/once", { action: "get" });
    assert.equal(once.status, 200);
    const nonce = (await once.json() as { body: { once: string } }).body.once;
    const response = await scalePost("/session", { action: "new", auth: MAC,
      hash: createHash("md5").update(`${MAC}:${SECRET}:${nonce}`).digest("hex"), currentfw: "101", enrich: "t" });
    assert.equal(response.status, 200);
    const session = (await response.json() as { body: Record<string, any> }).body;
    assert.deepEqual(Object.keys(session).sort(), ["sessionid", "syp"]);
    assert.deepEqual(Object.keys(session.syp), ["utc"]);
    const summary = await scalePost("/v2/summary", { action: "getforscale", sessionid: session.sessionid });
    assert.deepEqual(await summary.json(), { status: 0, body: [] });
    const measure = await scalePost("/measure", { action: "batchstore", sessionid: session.sessionid,
      macaddress: MAC, userid: String(baseline.sp.users[0].id), devtype: "1", category: "1", attribstatus: "0",
      measuregrps: JSON.stringify({ measuregrps: [{ meastime: Math.floor(Date.now() / 1000),
        measures: [{ type: 1, unit: -3, value: 70250 }] }] }) });
    assert.equal(measure.status, 200);
    const reading = await db.prepare("SELECT user_id,weight_value,weight_unit FROM readings").first();
    assert.equal(reading?.user_id, baseline.sp.users[0].id);
    assert.equal(reading?.weight_value, 70250);
    assert.equal(reading?.weight_unit, -3);
  } finally {
    store.close();
    rmSync(directory, { recursive: true, force: true });
  }
});
