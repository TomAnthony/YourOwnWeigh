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
test("WBS06 and WBS04 rosters append local members after the seed people", async () => {
  const dir = mkdtempSync(join(tmpdir(), "yow-roster-")),
    store = new LocalSqlite(join(dir, "db.sqlite3")),
    db = store.asD1();
  try {
    await db
      .prepare(
        "INSERT INTO scales(id,label,model,mac,secret) VALUES(1,'Demo','WBS06','020000000001','0123456789abcdef')",
      )
      .run();
    for (const [id, name, short, active] of [
      [5, "Alice", "ALI", 1],
      [6, "Bob", "BOB", 1],
      [7, "Retired", "RET", 0],
      [8, "Elsewhere", "ELS", 1],
    ] as const)
      await db
        .prepare(
          "INSERT INTO users(id,name,short_name,height_cm,age_years,sex,reference_weight_kg,created_at,active) VALUES(?,?,?,170,40,1,60,1700000001,?)",
        )
        .bind(id, name, short, active)
        .run();
    // Bob was chosen first; the retired user and a non-member are excluded.
    for (const [user, rank] of [[6, 1], [5, 2], [7, 3]])
      await db
        .prepare("INSERT INTO scale_users(scale_id,user_id,rank) VALUES(1,?,?)")
        .bind(user, rank)
        .run();
    const seed = [{ id: 900, sn: "OLD", ht: 1.7, cs: "11,6,2,10", ft: [] }];
    const result = (await roster({ DB: db }, {
      id: 1,
      model: "WBS06",
      roster_snapshot: JSON.stringify(seed),
    } as any)) as any[];
    assert.deepEqual(result.map((u) => u.id), [900, 6, 5]);
    assert.deepEqual(result[0], seed[0]); // Not imported locally: kept as is.
    assert.deepEqual(result[2], {
      fm: 3, att: 0, ft: [], cs: "11,6,2,10", cr: 1700000001,
      id: 5, sn: "ALI", fn: "Alice", ht: 1.7, agt: 40, sx: 1, wt: 60,
    });
    // A WBS06 with no Withings roster at all still gets its local users.
    const fresh = (await roster({ DB: db }, {
      id: 1, model: "WBS06", roster_snapshot: "[]",
    } as any)) as any[];
    assert.deepEqual(fresh.map((u) => [u.id, u.cs]), [[6, "2"], [5, "2"]]);
    // Body Cardio gets the same local users, with its own fm.
    const cardio = (await roster({ DB: db }, {
      id: 1, model: "WBS04", roster_snapshot: JSON.stringify(seed),
    } as any)) as any[];
    assert.deepEqual(cardio.map((u) => [u.id, u.fm]), [[900, undefined], [6, 131], [5, 131]]);
    assert.equal(cardio[2].cs, "11,6,2,10");
    // Other seeded models still send only their seed people.
    const other = (await roster({ DB: db }, {
      id: 1, model: "WBS03", roster_snapshot: JSON.stringify(seed),
    } as any)) as any[];
    assert.deepEqual(other.map((u) => u.id), [900]);
    // Nine people cannot be sent.
    const full = Array.from({ length: 8 }, (_, i) => ({ id: 1000 + i }));
    await assert.rejects(
      roster({ DB: db }, {
        id: 1, model: "WBS06", roster_snapshot: JSON.stringify(full),
      } as any),
      /at most eight/,
    );
  } finally {
    store.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
