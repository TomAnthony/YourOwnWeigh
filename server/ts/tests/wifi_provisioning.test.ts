import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LocalSqlite } from "../sqlite.ts";
import { handleApp } from "../app.ts";
import worker from "../../cloudflare/worker_ts.ts";

for (const runtime of ["local", "worker"]) {
  test(`${runtime}: Wi-Fi provisioning probe works before enrollment without opening a session`, async () => {
    const directory = mkdtempSync(join(tmpdir(), "yow-wifi-probe-"));
    const store = new LocalSqlite(join(directory, "test.sqlite3"));
    const db = store.asD1();
    const post = (url: string, action: string) => {
      const request = new Request(url, {
        method: "POST",
        body: new URLSearchParams({ action }),
      });
      return runtime === "local"
        ? handleApp(request, { DB: db, ALLOW_HTTP_SCALE: true })
        : worker.fetch(request, { DB: db, ALLOW_HTTP_SCALE: "1" });
    };
    const count = async (table: string) =>
      (await db.prepare(`SELECT COUNT(*) AS n FROM ${table}`).first<{ n: number }>())!.n;
    try {
      // Stock WBS05 probes /once after joining Wi-Fi, before saving credentials.
      // HTTP and HTTPS share the same form and response; neither needs a roster.
      for (const protocol of ["http", "https"]) {
        for (const path of ["/once", "/cgi-bin/once"]) {
          const response = await post(
            `${protocol}://scales.test${path}?appliver=100&appname=WBS05&apppfm=device`,
            "probe",
          );
          assert.equal(response.status, 200);
          assert.deepEqual(await response.json(), { status: 0 });
          assert.equal(response.headers.get("Cache-Control"), "no-store");
        }
      }
      for (const table of ["challenges", "device_sessions", "scales", "browser_auth_limits"])
        assert.equal(await count(table), 0, `Probe must not write ${table}`);

      // Normal challenge generation and action validation remain unchanged.
      const challenge = await post("https://scales.test/once", "get");
      assert.equal(challenge.status, 200);
      const result = await challenge.json() as { status: number; body: { once: string } };
      assert.equal(result.status, 0);
      assert.match(result.body.once, /^[0-9a-f]{24}$/);
      assert.equal(await count("challenges"), 1);
      assert.equal((await post("https://scales.test/once", "unknown")).status, 400);
    } finally {
      store.close();
      rmSync(directory, { recursive: true, force: true });
    }
  });
}
