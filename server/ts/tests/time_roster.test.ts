import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { zoneTriplet, roster } from "../scale_api.ts";
import { LocalSqlite } from "../sqlite.ts";
test("timezone contract covers DST boundaries, southern hemisphere and fractional offsets", () => {
  for (const v of JSON.parse(
    readFileSync("contracts/time/v1/vectors.json", "utf8"),
  ))
    assert.deepEqual(
      zoneTriplet(v.zone, v.utcSeconds),
      { goff: v.goff, dst: v.dst, ngoff: v.ngoff },
      v.zone + v.utcSeconds,
    );
});
test("roster overlays use metres and preserve people skipped during import", async () => {
  const dir = mkdtempSync(join(tmpdir(), "yow-roster-")),
    store = new LocalSqlite(join(dir, "db.sqlite3")),
    db = store.asD1();
  try {
    await db
      .prepare(
        "INSERT INTO scales(id,label,model,mac,secret) VALUES(1,'Demo','WBS06','020000000001','0123456789abcdef')",
      )
      .run();
    await db
      .prepare(
        "INSERT INTO users(id,name,short_name,height_cm,age_years,sex,reference_weight_kg,created_at) VALUES(101,'Edited','EDT',181,30,0,75,1)",
      )
      .run();
    await db
      .prepare("INSERT INTO scale_users(scale_id,user_id,rank) VALUES(1,101,0)")
      .run();
    const baseline = [
      { id: 101, ht: 1.8, sn: "OLD", cr: 1700000000 },
      { id: 102, ht: 1.65, sn: "KEP" },
    ];
    const result = (await roster({ DB: db }, {
      id: 1,
      roster_snapshot: JSON.stringify(baseline),
    } as any)) as any[];
    assert.equal(result[0].ht, 1.81);
    assert.equal(result[0].sn, "EDT");
    assert.equal(result[0].cr, 1700000000); // Keep the seed's original timestamp.
    assert.deepEqual(result[1], baseline[1]);
    await db
      .prepare(
        "UPDATE users SET reference_weight_kg=76,reference_weight_at=1793000000 WHERE id=101",
      )
      .run();
    const learned = (await roster({ DB: db }, {
      id: 1,
      roster_snapshot: JSON.stringify(baseline),
    } as any)) as any[];
    assert.equal(learned[0].wt, 76);
    assert.equal(learned[0].cr, 1793000000);
    assert.deepEqual(learned[1], baseline[1]);
  } finally {
    store.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
