import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LocalSqlite } from "../sqlite.ts";
import { handleScaleRequest } from "../scale_api.ts";
import { exportBackup, stageBackup } from "../backup.ts";

test("anonymous scale requests cannot write diagnostics, consume another peer's challenge, or lock its scale", async () => {
  const directory = mkdtempSync(join(tmpdir(), "yow-scale-security-"));
  const store = new LocalSqlite(join(directory, "test.sqlite3"));
  const db = store.asD1();
  const mac = "00:11:22:33:44:66";
  const secret = "synthetic-device-secret";
  const post = (path: string, fields: Record<string, string>, ip = "198.51.100.10") =>
    handleScaleRequest(new Request(`http://scale.test${path}`, {
      method: "POST",
      headers: { "X-YOW-Peer-IP": ip },
      body: new URLSearchParams(fields),
    }), { DB: db });
  const count = async (table: string) =>
    (await db.prepare(`SELECT COUNT(*) AS n FROM ${table}`).first<{ n: number }>())!.n;
  try {
    await db.prepare("INSERT INTO scales(id,label,model,mac,secret) VALUES(1,'Test','WBS03','001122334466',?)")
      .bind(secret).run();
    const first = await post("/once", { action: "get" });
    assert.equal(first?.status, 200);
    const nonce = (await first!.json() as { body: { once: string } }).body.once;
    const oversized = "x".repeat(120_000);
    for (let i = 0; i < 5; i++) {
      assert.equal((await post("/measure", {
        action: "batchstore", sessionid: "0".repeat(24), measuregrps: oversized,
      }))?.status, 403);
      assert.equal((await post("/session", {
        action: "new", auth: "invalid", hash: "0".repeat(32),
      }))?.status, 403);
    }
    assert.equal(await count("measure_rejections"), 0);
    assert.equal(await count("sync_audit"), 0);

    for (let i = 0; i < 40; i++)
      assert.equal((await post("/once", { action: "get" }, "203.0.113.20"))?.status,
        i < 32 ? 200 : 429);
    // More than the old 256-entry cap must not evict the scale's first nonce.
    for (let peer = 1; peer <= 9; peer++)
      for (let i = 0; i < 30; i++)
        assert.equal((await post("/once", { action: "get" }, `203.0.113.${peer}`))?.status, 200);
    assert.equal(await count("challenges"), 303);
    for (let i = 0; i < 10; i++)
      assert.equal((await post("/session", {
        action: "new", auth: mac, hash: "0".repeat(32),
      }, "203.0.113.20"))?.status, 403);
    const validHash = createHash("md5").update(`${mac}:${secret}:${nonce}`).digest("hex");
    assert.equal((await post("/session", {
      action: "new", auth: mac, hash: validHash,
    }, "203.0.113.20"))?.status, 403);
    const realScale = await post("/session", {
      action: "new", auth: mac, hash: validHash,
    });
    assert.equal(realScale?.status, 200);
    const sid = (await realScale!.json() as { body: { sessionid: string } }).body.sessionid;
    assert.equal((await post("/measure", {
      action: "batchstore", sessionid: sid, macaddress: mac,
      measuregrps: oversized,
    }))?.status, 400);
    const diagnostic = (await db.prepare("SELECT form_without_session FROM measure_rejections")
      .first<{ form_without_session: string }>())!.form_without_session;
    assert.ok(diagnostic.length < 500);
    assert.equal(JSON.parse(diagnostic).measuregrps_length, oversized.length);
    assert.equal(await count("measure_rejections"), 1);
    assert.equal(await count("sync_audit"), 2);
    const backup = await exportBackup(db);
    assert.deepEqual(backup.sections.sync_audit, []);
    assert.deepEqual(backup.sections.measure_rejections, []);
    await stageBackup(db, JSON.stringify(backup), "admin");
  } finally {
    store.close();
    rmSync(directory, { recursive: true, force: true });
  }
});

test("diagnostic retention bounds audit and rejected-measure rows", async () => {
  const directory = mkdtempSync(join(tmpdir(), "yow-retention-"));
  const store = new LocalSqlite(join(directory, "test.sqlite3"));
  try {
    const db = store.asD1();
    for (let i = 0; i < 1100; i++) {
      await db.prepare("INSERT INTO sync_audit(endpoint,outcome,received_at) VALUES('test','test',1)").run();
      await db.prepare("INSERT INTO measure_rejections(received_at,validation_stage,reason,form_without_session) VALUES(1,'test','test','{}')").run();
    }
    assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM sync_audit").first<{ n: number }>())!.n, 1000);
    assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM measure_rejections").first<{ n: number }>())!.n, 100);
  } finally {
    store.close();
    rmSync(directory, { recursive: true, force: true });
  }
});

test("failed scale sessions purge expired counters but preserve active browser limits", async () => {
  const directory = mkdtempSync(join(tmpdir(), "yow-session-limits-"));
  const store = new LocalSqlite(join(directory, "test.sqlite3"));
  const db = store.asD1();
  try {
    await db.prepare("INSERT INTO scales(id,label,model,mac,secret) VALUES(1,'Test','WBS03','001122334466','synthetic-device-secret')").run();
    const timestamp = Math.floor(Date.now() / 1000);
    await db.batch([
      db.prepare("INSERT INTO browser_auth_limits(key,window_start,attempts) VALUES('expired',?,2)")
        .bind(timestamp - 650),
      db.prepare("INSERT INTO browser_auth_limits(key,window_start,attempts) VALUES('active-login',?,8)")
        .bind(timestamp - 500),
    ]);
    const failedSession = () => handleScaleRequest(new Request("http://scale.test/session", {
      method: "POST",
      headers: { "X-YOW-Peer-IP": "203.0.113.9" },
      body: new URLSearchParams({
        action: "new", auth: "00:11:22:33:44:66", hash: "0".repeat(32),
      }),
    }), { DB: db });
    assert.equal((await failedSession())?.status, 403);
    assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM browser_auth_limits WHERE key='expired'")
      .first<{ n: number }>())!.n, 0);
    assert.equal((await db.prepare("SELECT attempts FROM browser_auth_limits WHERE key='active-login'")
      .first<{ attempts: number }>())!.attempts, 8);
    assert.equal((await failedSession())?.status, 403);
    const { results: counters } = await db.prepare(
      "SELECT attempts FROM browser_auth_limits WHERE key NOT IN ('expired','active-login')",
    ).all<{ attempts: number }>();
    assert.deepEqual(counters.map((row) => row.attempts), [2]);
  } finally {
    store.close();
    rmSync(directory, { recursive: true, force: true });
  }
});
