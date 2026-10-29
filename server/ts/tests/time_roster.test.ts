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
      { id: 101, ht: 1.8, sn: "OLD" },
      { id: 102, ht: 1.65, sn: "KEP" },
    ];
    const result = (await roster({ DB: db }, {
      id: 1,
      roster_snapshot: JSON.stringify(baseline),
    } as any)) as any[];
    assert.equal(result[0].ht, 1.81);
    assert.equal(result[0].sn, "EDT");
    assert.deepEqual(result[1], baseline[1]);
  } finally {
    store.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
