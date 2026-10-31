import test from "node:test";
import assert from "node:assert/strict";
import { once } from "node:events";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { Worker } from "node:worker_threads";
import { LocalSqlite } from "../sqlite.ts";

test(
  "a waiting local opener rechecks the schema and preserves groups written after another opener migrates",
  { timeout: 15000 },
  async () => {
    const dir = mkdtempSync(join(tmpdir(), "yow-concurrent-migration-"));
    const path = join(dir, "household.db");
    const old = new DatabaseSync(path);
    for (const file of [
      "0002_scale_core.sql",
      "0003_admin_sessions.sql",
      "0004_health_sync.sql",
      "0005_integrated_setup.sql",
      "0006_firmware_observations.sql",
      "0007_diagnostic_retention.sql",
    ])
      old.exec(
        readFileSync(
          new URL(`../../migrations/${file}`, import.meta.url),
          "utf8",
        ),
      );
    old.exec(`
    INSERT INTO users(id,name,short_name,height_cm,age_years,sex,reference_weight_kg,created_at)
      VALUES(17,'Alex','ALX',180,40,0,80,1700000000);
    INSERT INTO scales(id,label,model,mac,secret)
      VALUES(1,'Test','WBS13','020000000013','0123456789abcdef');
    INSERT INTO readings(id,scale_id,user_id,attribution,candidate_ids,attribstatus,
      meastime,weight_value,weight_unit,measures_json,payload_hash,first_received_at,last_received_at)
      VALUES(1,1,17,'device','[17]',0,1700000000,80000,-3,'[]','old',1700000000,1700000000);
    INSERT INTO health_sync_receipts VALUES(17,1,1700000001);
  `);
    old.close();

    // Pause a separate opener immediately before it obtains the writer lock.
    // With the old ordering it has already seen group_json missing at this point.
    // Let another opener migrate and save real group metadata, then resume it.
    const signal = new Int32Array(new SharedArrayBuffer(4));
    const waiting = new Worker(
      `
    const { parentPort, workerData } = require('node:worker_threads');
    const { DatabaseSync } = require('node:sqlite');
    const exec = DatabaseSync.prototype.exec;
    let paused = false;
    DatabaseSync.prototype.exec = function(sql) {
      if (!paused && sql === 'BEGIN IMMEDIATE') {
        paused = true;
        parentPort.postMessage('before-lock');
        if (Atomics.wait(new Int32Array(workerData.signal), 0, 0, 10000) === 'timed-out')
          throw new Error('Migration test barrier timed out');
      }
      return exec.call(this, sql);
    };
    (async () => {
      const { LocalSqlite } = await import(workerData.module);
      const store = new LocalSqlite(workerData.path);
      store.close();
      parentPort.postMessage('opened');
    })().catch(error => { throw error; });
  `,
      {
        eval: true,
        workerData: {
          path,
          signal: signal.buffer,
          module: new URL("../sqlite.ts", import.meta.url).href,
        },
      },
    );
    let first: LocalSqlite | undefined;
    try {
      assert.deepEqual(await once(waiting, "message"), ["before-lock"]);
      first = new LocalSqlite(path);
      const group = JSON.stringify({
        meastime: 1700000010,
        algo: 123,
        measures: [{ type: 11, value: 72, unit: 0, position: 6 }],
      });
      await first
        .prepare(
          `INSERT INTO readings(id,scale_id,user_id,attribution,candidate_ids,attribstatus,
      meastime,weight_value,weight_unit,measures_json,group_json,payload_hash,first_received_at,last_received_at)
      VALUES(2,1,17,'device','[17]',0,1700000010,NULL,NULL,?,?, 'new',1700000010,1700000010)`,
        )
        .bind(JSON.stringify(JSON.parse(group).measures), group)
        .run();
      const finished = once(waiting, "message");
      Atomics.store(signal, 0, 1);
      Atomics.notify(signal, 0);
      assert.deepEqual(await finished, ["opened"]);
      assert.deepEqual(
        {
          ...(await first
            .prepare(
              "SELECT group_json,weight_value,weight_unit FROM readings WHERE id=2",
            )
            .first()),
        },
        {
          group_json: group,
          weight_value: null,
          weight_unit: null,
        },
      );
      assert.equal(
        (await first
          .prepare("SELECT COUNT(*) AS n FROM readings")
          .first<any>())!.n,
        2,
      );
      assert.deepEqual(
        {
          ...(await first
            .prepare("SELECT * FROM health_sync_receipts")
            .first()),
        },
        {
          user_id: 17,
          reading_id: 1,
          synced_at: 1700000001,
        },
      );
    } finally {
      Atomics.store(signal, 0, 1);
      Atomics.notify(signal, 0);
      await waiting.terminate();
      first?.close();
      rmSync(dir, { recursive: true, force: true });
    }
  },
);
