import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { LocalSqlite } from "../sqlite.ts";
import { handleScaleRequest } from "../scale_api.ts";
import {
  firmwareObservation,
  sessionFirmware,
} from "../firmware_observation.ts";
import { scalesWorkspace } from "../integrated_ui.ts";

const now = () => Math.floor(Date.now() / 1000);
test("authenticated sync records either model's running version, including downgrade; bad/replayed requests cannot refresh it", async () => {
  const dir = mkdtempSync(join(tmpdir(), "yow-firmware-")),
    store = new LocalSqlite(join(dir, "db")),
    DB = store.asD1();
  const post = async (path: string, form: Record<string, string>) =>
    (await handleScaleRequest(
      new Request(`https://scale.test${path}`, {
        method: "POST",
        body: new URLSearchParams(form),
      }),
      { DB },
    ))!;
  try {
    for (const [id, model, version] of [
      [1, "WBS06", 127],
      [2, "WBS03", 102],
    ] as const) {
      const mac = `02000000000${id}`,
        secret = "0123456789abcdef";
      await DB.prepare(
        "INSERT INTO scales(id,label,model,mac,secret,settings_ready,screen_response,summary_response) VALUES(?,?,?,?,?,1,'{}','{}')",
      )
        .bind(id, model, model, mac, secret)
        .run();
      const openForm = async (v: number) => {
        const n = (
          (await (await post("/once", { action: "get" })).json()) as any
        ).body.once;
        return {
          action: "new",
          auth: mac,
          currentfw: String(v),
          hash: createHash(model === "WBS06" ? "sha256" : "md5")
            .update(`${mac}:${secret}:${n}`)
            .digest("hex"),
          ...(model === "WBS06" ? { hashmethod: "sha256" } : {}),
        } as Record<string, string>;
      };
      const read = () =>
        DB.prepare(
          "SELECT firmware_version,firmware_confirmed_at,firmware_source FROM scales WHERE id=?",
        )
          .bind(id)
          .first<any>();
      const form = await openForm(version),
        path = `/session?appliver=${version}&appname=${model}`;
      assert.equal(
        (await post(path, { ...form, hash: "0".repeat(form.hash.length) }))
          .status,
        403,
      );
      assert.equal((await read()).firmware_version, null);
      assert.equal((await post(path, form)).status, 200);
      const initial = await read();
      assert.equal(initial.firmware_version, version);
      assert.equal(initial.firmware_source, "wifi");
      assert.ok(Math.abs(initial.firmware_confirmed_at - now()) < 5);
      assert.equal(
        (await post(path, { ...form, currentfw: "999" })).status,
        403,
      );
      assert.deepEqual(await read(), initial);
      // An old export must not roll the observed version back.
      await firmwareObservation(
        DB,
        id,
        version - 1,
        now() - 60,
        "bluetooth",
      ).run();
      assert.deepEqual(await read(), initial);
      // A real subsequent downgrade DOES supersede the version. This is not MAX(version).
      assert.equal(
        (await post("/session", await openForm(version - 1))).status,
        200,
      );
      assert.equal((await read()).firmware_version, version - 1);
      const before = await read();
      for (const invalid of ["", "0", "16777215", "abc", "127.5"]) {
        assert.equal(
          (
            await post("/session", {
              ...(await openForm(version)),
              currentfw: invalid,
            })
          ).status,
          200,
        );
        assert.deepEqual(await read(), before);
      }
    }
  } finally {
    store.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("firmware query fallback is model-bound and ignores duplicate or contradictory reports", () => {
  const read = (query: string) =>
    sessionFirmware(new URLSearchParams(query), "WBS06");
  assert.equal(read("appliver=127&appname=WBS06"), 127);
  assert.equal(read("currentfw=127"), 127);
  for (const q of [
    "appliver=127",
    "appname=WBS03&appliver=127",
    "currentfw=127&currentfw=128",
    "currentfw=127&appliver=128",
    "currentfw=127&appname=WBS03",
    "currentfw=16777215",
  ])
    assert.equal(read(q), null, q);
});

test("existing BLE exports migrate once with their original time; scale cards expose source/time or unknown", async () => {
  const dir = mkdtempSync(join(tmpdir(), "yow-firmware-migrate-")),
    path = join(dir, "db");
  const old = new DatabaseSync(path),
    timestamp = now() - 86400;
  old.exec(
    readFileSync(
      new URL("../../migrations/0002_scale_core.sql", import.meta.url),
      "utf8",
    ),
  );
  old
    .prepare(
      "INSERT INTO scales(label,model,mac,secret,ble_firmware_version,ble_captured_at) VALUES('Test','WBS06','020000000006','0123456789abcdef',126,?)",
    )
    .run(timestamp);
  old.close();
  try {
    for (let i = 0; i < 2; i++) {
      const store = new LocalSqlite(path);
      try {
        const s = await store.prepare("SELECT * FROM scales").first<any>();
        assert.equal(s.firmware_version, 126);
        assert.equal(s.firmware_confirmed_at, timestamp);
        assert.equal(s.firmware_source, "bluetooth");
        const page = scalesWorkspace([s], "test-csrf");
        assert.match(page, /Firmware.*role="tooltip"/);
        assert.match(page, /via Bluetooth/);
        assert.match(page, /<td>v126<\/td>/);
        assert.match(
          scalesWorkspace([{ ...s, firmware_version: null }], "test"),
          /Not Yet Confirmed/,
        );
      } finally {
        store.close();
      }
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
