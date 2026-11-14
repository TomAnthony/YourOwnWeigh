import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LocalSqlite } from "../sqlite.ts";
import { handleApp, type AppEnv } from "../app.ts";
import { batteryLevel } from "../scale_api.ts";
import { dashboardPage, LOW_BATTERY, scaleBatteries } from "../ui.ts";
import { scalesWorkspace } from "../integrated_ui.ts";

test("battery level accepts exactly one whole percentage", () => {
  const level = (query: string) => batteryLevel(new URLSearchParams(query));
  assert.equal(level("batterylvl=63"), 63);
  assert.equal(level("batterylvl=0"), 0);
  assert.equal(level("batterylvl=100"), 100);
  assert.equal(level("batterylvl=007"), 7);
  for (const bad of [
    "",
    "batterylvl=",
    "batterylvl=101",
    "batterylvl=-1",
    "batterylvl=6.5",
    "batterylvl=1e2",
    "batterylvl=%2063",
    "batterylvl=1000",
    "batterylvl=50&batterylvl=50",
  ])
    assert.equal(level(bad), null, bad);
});

// Synthetic identity; the WS-30 session is the smallest complete Wi-Fi session.
const MAC = "00:11:22:33:44:66";
const SECRET = "0123456789abcdef";

test("a Wi-Fi session stores the reported battery level and keeps it when absent or invalid", async () => {
  const directory = mkdtempSync(join(tmpdir(), "yow-battery-"));
  const store = new LocalSqlite(join(directory, "test.sqlite3"));
  try {
    const db = store.asD1();
    const env: AppEnv = { DB: db, ALLOW_HTTP_SCALE: true };
    await db
      .prepare(
        "INSERT INTO scales(id,label,model,mac,secret) VALUES(1,'Bathroom','WBS03','001122334466',?)",
      )
      .bind(SECRET)
      .run();
    const post = (path: string, fields: Record<string, string>) =>
      handleApp(
        new Request(`http://scales.test${path}`, {
          method: "POST",
          body: new URLSearchParams(fields),
        }),
        env,
      );
    const session = async (extra: Record<string, string>) => {
      const once = (
        (await (await post("/once", { action: "get" })).json()) as {
          body: { once: string };
        }
      ).body.once;
      const response = await post("/session", {
        action: "new",
        auth: MAC,
        hash: createHash("md5")
          .update(`${MAC}:${SECRET}:${once}`)
          .digest("hex"),
        currentfw: "101",
        ...extra,
      });
      assert.equal(response.status, 200, await response.clone().text());
    };
    const stored = async () =>
      (await db
        .prepare("SELECT battery_level FROM scales WHERE id=1")
        .first<{ battery_level: number | null }>())!.battery_level;
    assert.equal(await stored(), null);
    await session({ batterylvl: "63" });
    assert.equal(await stored(), 63);
    await session({ batterylvl: "12" });
    assert.equal(await stored(), 12);
    await session({});
    assert.equal(await stored(), 12);
    await session({ batterylvl: "250" });
    assert.equal(await stored(), 12);
  } finally {
    store.close();
    rmSync(directory, { recursive: true, force: true });
  }
});

const reported = 1793000000;
const scale = (overrides: Record<string, unknown>) => ({
  id: 1,
  label: "Bathroom",
  model: "WBS06",
  mac: "001122334466",
  secret: "0123456789abcdef",
  settings_ready: 1,
  battery_level: null,
  last_session_at: reported,
  ...overrides,
});

test("dashboard shows one battery badge per reporting scale, flagged at the low threshold", () => {
  assert.equal(scaleBatteries([scale({})]), "");
  const html = scaleBatteries([
    scale({ label: "Bathroom", battery_level: 82 }),
    scale({ label: "Guest <Bath>", battery_level: LOW_BATTERY }),
    scale({ label: "Cardio", model: "WBS04", battery_level: 5 }),
    scale({ label: "Unknown", battery_level: null }),
    scale({ label: "Above", battery_level: LOW_BATTERY + 1 }),
  ]);
  assert.equal(html.match(/class="badge scale-battery/g)?.length, 4);
  assert.equal(html.match(/class="badge scale-battery warn"/g)?.length, 2);
  assert.match(
    html,
    /<span>Bathroom<\/span><svg[^]*?<span>82 %<\/span><\/span>/,
  );
  assert.match(
    html,
    /Guest &lt;Bath&gt;[^]*?<span>20 %<\/span><span>· Replace Batteries<\/span>/,
  );
  assert.match(html, /Cardio[^]*?<span>5 %<\/span><span>· Charge Soon<\/span>/);
  assert.doesNotMatch(html, /Unknown/);
  assert.doesNotMatch(html, /Above[^]*?Replace/);
  assert.match(html, /title="Battery reported /);
  assert.match(
    dashboardPage([], "kg", [scale({ battery_level: 82 })]),
    /class="scale-batteries"/,
  );
  assert.doesNotMatch(dashboardPage([], "kg"), /scale-batteries/);
});

test("scale card always has a Battery row, Not Yet Reported until the first level", () => {
  assert.match(
    scalesWorkspace([scale({})], "csrf"),
    /<th>Battery<\/th><td>Not Yet Reported<\/td>/,
  );
  const ok = scalesWorkspace([scale({ battery_level: 82 })], "csrf");
  assert.match(ok, /<th>Battery<\/th><td>82 %<span class="hint">Reported /);
  assert.doesNotMatch(ok, /Replace Batteries/);
  const low = scalesWorkspace(
    [scale({ model: "WBS04", battery_level: 12 })],
    "csrf",
  );
  assert.match(
    low,
    /<th>Battery<\/th><td>12 % <span class="badge warn">Charge Soon<\/span><span class="hint">Reported /,
  );
});
