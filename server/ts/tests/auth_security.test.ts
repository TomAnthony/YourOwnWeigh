import test from "node:test";
import assert from "node:assert/strict";
import { pbkdf2Sync } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LocalSqlite } from "../sqlite.ts";
import { handleApp } from "../app.ts";

test("expired browser sessions are purged and login failures are isolated by peer", async () => {
  const directory = mkdtempSync(join(tmpdir(), "yow-login-security-"));
  const store = new LocalSqlite(join(directory, "test.sqlite3"));
  const db = store.asD1();
  try {
    const salt = Buffer.alloc(16, 7);
    const hash = pbkdf2Sync("correct-password", salt, 100000, 32, "sha256").toString("hex");
    await db.prepare("INSERT INTO settings(key,value) VALUES('admin_password',?)")
      .bind(`pbkdf2_sha256$100000$${salt.toString("hex")}$${hash}`).run();
    await db.prepare("INSERT INTO admin_sessions(token_hash,csrf,is_admin,auth_version,expires_at) VALUES('expired','expired',0,0,1)").run();
    const page = await handleApp(new Request("https://local.test/login"), { DB: db });
    const cookie = page.headers.get("set-cookie")!.split(";")[0];
    const csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(await page.text())![1];
    assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM admin_sessions WHERE expires_at=1")
      .first<{ n: number }>())!.n, 0);
    const login = (ip: string, password: string) => handleApp(new Request("https://local.test/login", {
      method: "POST",
      headers: { Cookie: cookie, Origin: "https://local.test", "X-YOW-Peer-IP": ip },
      body: new URLSearchParams({ _csrf: csrf, password }),
    }), { DB: db });
    for (let i = 0; i < 20; i++)
      assert.match((await login("203.0.113.8", "wrong")).headers.get("location") ?? "", /Invalid.password/);
    assert.match((await login("203.0.113.8", "correct-password")).headers.get("location") ?? "", /Too.many.attempts/);
    assert.equal((await login("198.51.100.2", "correct-password")).headers.get("location"), "/?notice=Signed+in");
  } finally {
    store.close();
    rmSync(directory, { recursive: true, force: true });
  }
});
