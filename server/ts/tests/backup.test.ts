import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LocalSqlite } from "../sqlite.ts";
import { exportBackup, stageBackup, commitBackup } from "../backup.ts";
const hash = "a".repeat(64);
async function seed(db: LocalSqlite, scaleId = 7, readingId = 11) {
  await db
    .prepare("INSERT INTO settings VALUES('display_weight_unit','kg')")
    .run();
  await db
    .prepare("INSERT INTO settings VALUES('admin_password',?)")
    .bind(`pbkdf2_sha256$100000$${"0".repeat(32)}$${"1".repeat(64)}`)
    .run();
  await db
    .prepare(
      "INSERT INTO users(id,name,short_name,height_cm,age_years,sex,reference_weight_kg,created_at) VALUES(101,'Alex','ALX',170,30,0,70,1)",
    )
    .run();
  await db
    .prepare(
      "INSERT INTO scales(id,label,model,mac,secret) VALUES(?,'Bathroom','WBS03','020000000003','0123456789abcdef')",
    )
    .bind(scaleId)
    .run();
  await db
    .prepare("INSERT INTO scale_users VALUES(?,101,1)")
    .bind(scaleId)
    .run();
  await db
    .prepare(
      "INSERT INTO readings(id,scale_id,user_id,attribution,candidate_ids,attribstatus,meastime,time_quality,weight_value,weight_unit,measures_json,payload_hash,first_received_at,last_received_at) VALUES(?,?,101,'assigned','[]',0,1793000000,'trusted',70000,-3,'[]',?,1793000000,1793000000)",
    )
    .bind(readingId, scaleId, hash)
    .run();
  await db
    .prepare("INSERT INTO health_sync_receipts VALUES(101,?,1793000001)")
    .bind(readingId)
    .run();
  await db
    .prepare(
      "INSERT INTO sync_audit(scale_id,endpoint,outcome,received_at) VALUES(?,'measure','committed',1793000000)",
    )
    .bind(scaleId)
    .run();
}
test("backup merge remaps IDs, preserves local edits/receipts, and repeat merge deduplicates", async () => {
  const dir = mkdtempSync(join(tmpdir(), "yow-backup-")),
    source = new LocalSqlite(join(dir, "source.db")),
    target = new LocalSqlite(join(dir, "target.db"));
  try {
    await seed(source);
    await seed(target, 2, 3);
    await target
      .prepare("UPDATE users SET name='Edited Locally' WHERE id=101")
      .run();
    const backup = await exportBackup(source.asD1());
    assert.equal(backup.sections.scales[0].id, 7);
    assert.equal(backup.accessSettings.length, 1);
    assert.equal("admin_sessions" in backup.sections, false);
    for (let n = 0; n < 2; n++) {
      const preview = await stageBackup(
        target.asD1(),
        JSON.stringify(backup),
        "admin",
      );
      await commitBackup(
        target.asD1(),
        preview.id,
        preview.digest,
        "admin",
        "merge",
        false,
      );
    }
    assert.equal(
      (await target.prepare("SELECT count(*) n FROM readings").first<any>()).n,
      1,
    );
    assert.equal(
      (await target.prepare("SELECT count(*) n FROM sync_audit").first<any>())
        .n,
      1,
    );
    assert.equal(
      (await target.prepare("SELECT name FROM users WHERE id=101").first<any>())
        .name,
      "Edited Locally",
    );
    assert.deepEqual(
      {
        ...(await target
          .prepare("SELECT user_id,reading_id FROM health_sync_receipts")
          .first()),
      },
      { user_id: 101, reading_id: 3 },
    );
    const p = await stageBackup(target.asD1(), JSON.stringify(backup), "admin");
    await assert.rejects(
      commitBackup(target.asD1(), p.id, p.digest, "other", "replace", false),
      /confirmation/,
    );
    await commitBackup(
      target.asD1(),
      p.id,
      p.digest,
      "admin",
      "replace",
      false,
    );
    assert.equal(
      (await target.prepare("SELECT id FROM scales").first<any>()).id,
      7,
    );
    assert.equal(
      (await target.prepare("SELECT name FROM users").first<any>()).name,
      "Alex",
    );
    await assert.rejects(
      commitBackup(target.asD1(), p.id, p.digest, "admin", "replace", true),
      /expired/,
    );
  } finally {
    source.close();
    target.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
test("malformed imports and a failing final batch never partially replace the household", async () => {
  const dir = mkdtempSync(join(tmpdir(), "yow-backup-")),
    store = new LocalSqlite(join(dir, "db"));
  try {
    await seed(store);
    const backup = await exportBackup(store.asD1());
    const invalid = structuredClone(backup);
    invalid.sections.readings[0].user_id = 999;
    await assert.rejects(
      stageBackup(store.asD1(), JSON.stringify(invalid), "admin"),
      /referenced user/,
    );
    const p = await stageBackup(store.asD1(), JSON.stringify(backup), "admin");
    // Simulate storage corruption after preview. The FK violation occurs after
    // deletes in the commit batch, proving those deletes roll back as well.
    await store
      .prepare(
        "UPDATE backup_staging_rows SET row_json=json_set(row_json,'$.user_id',999) WHERE import_id=? AND section='readings'",
      )
      .bind(p.id)
      .run();
    await assert.rejects(
      commitBackup(store.asD1(), p.id, p.digest, "admin", "replace", false),
    );
    assert.equal(
      (await store.prepare("SELECT count(*) n FROM readings").first<any>()).n,
      1,
    );
    assert.equal(
      (await store.prepare("SELECT count(*) n FROM users").first<any>()).n,
      1,
    );
  } finally {
    store.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("firmware observations survive restore and pre-tracking backups still import", async () => {
  const dir = mkdtempSync(join(tmpdir(), "yow-backup-firmware-"));
  const source = new LocalSqlite(join(dir, "source")),
    target = new LocalSqlite(join(dir, "target"));
  try {
    await seed(source);
    const timestamp = Math.floor(Date.now() / 1000) - 3600;
    await source
      .prepare(
        "UPDATE scales SET ble_firmware_version=101,ble_captured_at=?,firmware_version=102,firmware_confirmed_at=?,firmware_source='wifi'",
      )
      .bind(timestamp - 60, timestamp)
      .run();
    const backup = await exportBackup(source.asD1());
    const restore = async (data: unknown) => {
      const preview = await stageBackup(
        target.asD1(),
        JSON.stringify(data),
        "test-admin",
      );
      await commitBackup(
        target.asD1(),
        preview.id,
        preview.digest,
        "test-admin",
        "replace",
        false,
      );
      return target
        .prepare(
          "SELECT firmware_version,firmware_confirmed_at,firmware_source FROM scales",
        )
        .first<any>();
    };
    assert.deepEqual(
      { ...(await restore(backup)) },
      {
        firmware_version: 102,
        firmware_confirmed_at: timestamp,
        firmware_source: "wifi",
      },
    );
    const old = structuredClone(backup);
    for (const key of [
      "firmware_version",
      "firmware_confirmed_at",
      "firmware_source",
    ])
      delete old.sections.scales[0][key];
    assert.deepEqual(
      { ...(await restore(old)) },
      {
        firmware_version: 101,
        firmware_confirmed_at: timestamp - 60,
        firmware_source: "bluetooth",
      },
    );
    const invalid = structuredClone(backup);
    invalid.sections.scales[0].firmware_source = "unknown";
    await assert.rejects(
      stageBackup(target.asD1(), JSON.stringify(invalid), "test-admin"),
      /firmware observation/,
    );
  } finally {
    source.close();
    target.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
