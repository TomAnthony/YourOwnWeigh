import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ws30MD5 } from "../ws30_md5.ts";
import { LocalSqlite } from "../sqlite.ts";
import { handleApp, type AppEnv } from "../app.ts";
import worker from "../../cloudflare/worker_ts.ts";

test("WS-30 MD5 matches RFC 1321 vectors and Node across padding boundaries", () => {
  for (const [input, expected] of [
    ["", "d41d8cd98f00b204e9800998ecf8427e"],
    ["a", "0cc175b9c0f1b6a831c399e269772661"],
    ["abc", "900150983cd24fb0d6963f7d28e17f72"],
    ["message digest", "f96b697d7cb7938d525a2f31aaf161d0"],
    ["abcdefghijklmnopqrstuvwxyz", "c3fcd3d76192e4007dfb496cca67e13b"],
  ]) assert.equal(ws30MD5(input), expected);
  for (const size of [0, 1, 31, 54, 55, 56, 57, 63, 64, 65, 119, 120, 255, 1024]) {
    const input = "0123456789é🙂".repeat(size);
    assert.equal(ws30MD5(input), createHash("md5").update(input).digest("hex"));
  }
});

// Synthetic identities and values; wire shapes come from the owner's v101 trace.
const MAC = "00:11:22:33:44:66";
const SECRET = "0123456789abcdef";
const hash = (nonce: string, mac = MAC, secret = SECRET, algorithm = "md5") =>
  createHash(algorithm).update(`${mac}:${secret}:${nonce}`).digest("hex");

async function harness() {
  const directory = mkdtempSync(join(tmpdir(), "yow-ws30-"));
  const store = new LocalSqlite(join(directory, "test.sqlite3"));
  const db = store.asD1();
  const env: AppEnv = { DB: db, ALLOW_HTTP_SCALE: true };
  await db.prepare("INSERT INTO scales(id,label,model,mac,secret) VALUES(1,'Test WS-30','WBS03','001122334466',?)")
    .bind(SECRET).run();
  const post = (path: string, fields: Record<string, string> | URLSearchParams) => handleApp(
    new Request(`http://scales.test${path}`, { method: "POST", body: new URLSearchParams(fields) }), env);
  const nonce = async () => {
    const response = await post("/once", { action: "get" });
    assert.equal(response.status, 200);
    return (await response.json() as { body: { once: string } }).body.once;
  };
  const form = (n: string) => ({ action: "new", auth: MAC, hash: hash(n), mfgid: "262153",
    currentfw: "101", batterylvl: "63", duration: "300", zreboot: "1", trigger: "weather", enrich: "t" });
  const open = async () => {
    const response = await post("/session", form(await nonce()));
    assert.equal(response.status, 200, await response.clone().text());
    return (await response.json() as { body: Record<string, any> }).body;
  };
  const cleanup = () => { store.close(); rmSync(directory, { recursive: true, force: true }); };
  return { store, db, env, post, nonce, form, open, cleanup };
}

test("WS-30 syncs without WBS06 fixtures, preserves settings, and commits/deduplicates readings", async () => {
  const h = await harness();
  try {
    await h.db.prepare("INSERT INTO users(id,name,short_name,height_cm,age_years,sex,reference_weight_kg,created_at) " +
      "VALUES(17,'Test Person','TST',180,40,0,73,1)").run();
    // Even stale WBS06-style settings must never go to this model.
    await h.db.prepare("UPDATE scales SET settings_ready=1,roster_enabled=1 WHERE id=1").run();
    const session = await h.open();
    assert.deepEqual(Object.keys(session).sort(), ["sessionid", "syp"]);
    assert.deepEqual(Object.keys(session.syp), ["utc"]);
    assert.ok(Math.abs(session.syp.utc - Date.now() / 1000) < 5);
    const sid = session.sessionid;
    const summary = await h.post("/v2/summary", { action: "getforscale", sessionid: sid });
    assert.deepEqual(await summary.json(), { status: 0, body: [] });
    await h.db.prepare("UPDATE scales SET weather_response=? WHERE id=1").bind(JSON.stringify({ status: 0, body: { series: [{ temp: 99 }] } })).run();
    const weather = await h.post("/v2/weather", { action: "getforecast", sessionid: sid });
    assert.deepEqual(await weather.json(), { status: 0, body: { series: [] } });
    const timestamp = Math.floor(Date.now() / 1000);
    const fields = { action: "batchstore", sessionid: sid, macaddress: MAC, userid: "17",
      devtype: "1", category: "1", attribstatus: "0", measuregrps: JSON.stringify({ measuregrps: [
        { meastime: timestamp, measures: [{ value: 73250, type: 1, unit: -3 }] },
        { meastime: timestamp - 60, measures: [{ value: 73400, type: 1, unit: -3 }] },
      ] }) };
    for (let attempt = 0; attempt < 2; attempt++) {
      const response = await h.post("/measure", fields);
      assert.equal(response.status, 200);
      const ack = await response.json() as { status: number; body: { updatetime: number; measuregrps: unknown[] }[] };
      assert.equal(ack.status, 0);
      assert.deepEqual(ack.body[0].measuregrps, []);
      assert.ok(Math.abs(ack.body[0].updatetime - Date.now() / 1000) < 5);
    }
    const readings = (await h.db.prepare("SELECT * FROM readings ORDER BY meastime DESC").all()).results;
    assert.equal(readings.length, 2);
    assert.equal(readings[0].weight_value, 73250);
    assert.equal(readings[0].weight_unit, -3);
    assert.equal(readings[0].meastime, timestamp);
    assert.equal(readings[0].user_id, 17);
    assert.equal(readings[0].attribution, "device");
    assert.equal(readings[0].time_quality, "trusted");
    assert.equal(readings[0].attempts, 2);
    assert.equal((await h.post("/measure", { ...fields, userid: "999" })).status, 200);
    const unassigned = await h.db.prepare("SELECT user_id,attribution,candidate_ids FROM readings WHERE attribution='unassigned' LIMIT 1").first();
    assert.deepEqual({ ...unassigned }, { user_id: null, attribution: "unassigned", candidate_ids: "[999]" });
    const unknown = new URLSearchParams(fields); unknown.delete("userid");
    assert.equal((await h.post("/measure", unknown)).status, 200);
    const ambiguous = new URLSearchParams(fields); ambiguous.append("userid", "18");
    assert.equal((await h.post("/measure", ambiguous)).status, 200);
    assert.equal((await h.post("/measure", { ...fields, measuregrps: '{"measuregrps":[]}' })).status, 400);
    assert.equal((await h.post("/measure", { ...fields, macaddress: "00:11:22:33:44:77" })).status, 403);
    assert.equal((await h.post("/measure", { ...fields, sessionid: "0".repeat(24) })).status, 403);

    // Simulated storage failure cannot produce a success acknowledgement.
    const db = h.env.DB;
    h.env.DB = { prepare: db.prepare.bind(db), batch: async () => { throw new Error("disk failure"); } } as unknown as D1Database;
    await assert.rejects(h.post("/measure", fields), /disk failure/);
    h.env.DB = db;
    for (let attempt = 0; attempt < 2; attempt++) {
      assert.equal((await h.post("/session", { action: "delete", sessionid: sid })).status, 200);
    }
    assert.equal((await h.post("/measure", fields)).status, 403);
    await h.db.prepare("UPDATE scales SET time_zone='Europe/Berlin' WHERE id=1").run();
    const zoned = await h.open();
    assert.ok([3600, 7200].includes(zoned.ctp.goff));
    assert.ok(zoned.ctp.dst > timestamp);
    assert.equal(zoned.ind, undefined);
    assert.equal(zoned.sp, undefined);
  } finally { h.cleanup(); }
});

test("WS-30 authentication is model-bound, expires, consumes nonces and rejects replay", async () => {
  const h = await harness();
  try {
    const n = await h.nonce();
    assert.equal((await h.post("/session", { ...h.form(n), hash: "0".repeat(32) })).status, 403);
    assert.equal((await h.post("/session", { ...h.form(n), hashmethod: "sha256", hash: hash(n, MAC, SECRET, "sha256") })).status, 403);
    assert.equal((await h.post("/session", h.form(n))).status, 200);
    assert.equal((await h.post("/session", h.form(n))).status, 403);
    const expired = await h.nonce();
    await h.db.prepare("UPDATE challenges SET issued_at=0 WHERE nonce=?").bind(expired).run();
    assert.equal((await h.post("/session", h.form(expired))).status, 403);
    const session = await h.open();
    await h.db.prepare("UPDATE device_sessions SET expires_at=0 WHERE token=?").bind(session.sessionid).run();
    assert.equal((await h.post("/v2/summary", { action: "getforscale", sessionid: session.sessionid })).status, 403);
    await h.db.prepare("INSERT INTO scales(id,label,model,mac,secret,settings_ready,screen_response,summary_response) " +
      "VALUES(2,'Body','WBS06','001122334477',?,1,'{}','{}')").bind(SECRET).run();
    const next = await h.nonce();
    const mac = "00:11:22:33:44:77";
    assert.equal((await h.post("/session", { action: "new", auth: mac, hash: hash(next, mac) })).status, 403);
    assert.equal((await h.post("/session", { action: "new", auth: mac, hashmethod: "sha256", hash: hash(next, mac, SECRET, "sha256") })).status, 200);
    await h.db.prepare("UPDATE scales SET model='UNKNOWN' WHERE id=1").run();
    assert.equal((await h.post("/session", h.form(await h.nonce()))).status, 403);
  } finally { h.cleanup(); }
});

test("Worker always accepts HTTP scale traffic while dashboard/API remain HTTPS", async () => {
  const h = await harness();
  const request = (path = "/once", method = "POST") => new Request(`http://scales.test${path}`,
    { method, body: method === "POST" ? new URLSearchParams({ action: "get" }) : undefined });
  try {
    for (const value of [undefined, "0", "false"]) {
      assert.equal((await worker.fetch(request(), { DB: h.db, ALLOW_HTTP_SCALE: value })).status, 200);
    }
    assert.equal((await worker.fetch(request(), { DB: h.db, ALLOW_HTTP_SCALE: "1" })).status, 200);
    for (const path of ["/", "/scales", "/api/users/TST/weights"]) {
      const response = await worker.fetch(request(path, "GET"), { DB: h.db, ALLOW_HTTP_SCALE: "1" });
      assert.equal(response.status, 308);
      assert.equal(response.headers.get("location"), `https://scales.test${path}`);
    }
    assert.equal((await worker.fetch(request("/once", "GET"), { DB: h.db, ALLOW_HTTP_SCALE: "1" })).status, 404);
    await h.db.prepare("INSERT INTO settings(key,value) VALUES('scale_api_enabled','0')").run();
    assert.equal((await worker.fetch(request(), { DB: h.db, ALLOW_HTTP_SCALE: "1" })).status, 200);
  } finally { h.cleanup(); }
});
