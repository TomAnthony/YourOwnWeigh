import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LocalSqlite } from "../sqlite.ts";
import { handleApp, type AppEnv } from "../app.ts";

async function harness() {
  const directory = mkdtempSync(join(tmpdir(), "yow-scale-users-"));
  const store = new LocalSqlite(join(directory, "test.sqlite3"));
  const env: AppEnv = {
    DB: store.asD1(),
    ALLOW_HTTP_SCALE: true,
    YOW_BOOTSTRAP_TOKEN: "dummy-test-bootstrap-token",
  };
  let cookie = "";
  let csrf = "";
  const request = async (
    path: string,
    method = "GET",
    fields?: URLSearchParams,
  ) => {
    const headers: Record<string, string> = {};
    if (cookie) headers.Cookie = cookie;
    if (fields) headers["Content-Type"] = "application/x-www-form-urlencoded";
    return handleApp(
      new Request(`https://local.test${path}`, {
        method,
        headers,
        body: fields?.toString(),
      }),
      env,
    );
  };
  const post = (path: string, fields: Record<string, string>) =>
    request(path, "POST", new URLSearchParams({ _csrf: csrf, ...fields }));
  const first = await request("/setup");
  cookie = first.headers.get("set-cookie")!.split(";")[0];
  csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(await first.text())![1];
  const setup = await post("/setup", {
    bootstrap_token: "dummy-test-bootstrap-token",
    password: "password-123",
    confirm: "password-123",
  });
  cookie = setup.headers.get("set-cookie")!.split(";")[0];
  const dashboard = await request("/");
  csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(await dashboard.text())![1];
  await env.DB.prepare(
    "INSERT INTO scales(id,label,model,mac,secret,settings_ready,time_zone) VALUES(1,'Bathroom','WBS06','020000000001','0123456789abcdef',1,'UTC')",
  ).run();
  return {
    env,
    request,
    post,
    csrf,
    db: env.DB,
    cleanup: () => {
      store.close();
      rmSync(directory, { recursive: true, force: true });
    },
  };
}

async function addReading(
  db: D1Database,
  id: number,
  candidateIds: number[],
  timestamp: number,
) {
  await db
    .prepare(
      "INSERT INTO readings(id,scale_id,user_id,attribution,candidate_ids,attribstatus,meastime,weight_value,weight_unit,measures_json,group_json,payload_hash,first_received_at,last_received_at) VALUES(?,1,NULL,'unassigned',?,0,?,71209,-3,?,?,?,?,?)",
    )
    .bind(
      id,
      JSON.stringify(candidateIds),
      timestamp,
      JSON.stringify([{ value: 71209, type: 1, unit: -3 }]),
      JSON.stringify({
        meastime: timestamp,
        measures: [{ value: 71209, type: 1, unit: -3 }],
      }),
      `hash-${id}`,
      timestamp,
      timestamp,
    )
    .run();
}

test("an unassigned reading exposes its scale user ID and can be named locally", async () => {
  const h = await harness();
  try {
    await addReading(h.db, 1, [26954592], 1793937548);
    const page = await (await h.request("/readings")).text();
    assert.match(page, /Scale ID/);
    assert.match(page, /26954592/);
    assert.match(page, /Name Scale User/);

    const named = await h.post("/readings/1/name-scale-user", {
      candidate_id: "26954592",
      name: "Sam",
      short_name: "SAM",
      height_cm: "181",
      birth_date: "1985-01-01",
      sex: "0",
      reference_weight_kg: "71.209",
    });
    assert.equal(named.status, 303);

    const user = await h.db
      .prepare("SELECT id,name,short_name FROM users WHERE id=?")
      .bind(26954592)
      .first<{ id: number; name: string; short_name: string }>();
    assert.deepEqual(user ? { ...user } : null, {
      id: 26954592,
      name: "Sam",
      short_name: "SAM",
    });
    const reading = await h.db
      .prepare("SELECT user_id,attribution FROM readings WHERE id=1")
      .first<{ user_id: number; attribution: string }>();
    assert.equal(reading?.user_id, 26954592);
    assert.equal(reading?.attribution, "manual");
    const membership = await h.db
      .prepare(
        "SELECT COUNT(*) AS count FROM scale_users WHERE scale_id=1 AND user_id=?",
      )
      .bind(26954592)
      .first<{ count: number }>();
    assert.equal(membership?.count, 1);
    const recognition = await h.db
      .prepare(
        "SELECT reference_weight_kg,reference_weight_at FROM users WHERE id=?",
      )
      .bind(26954592)
      .first<{ reference_weight_kg: number; reference_weight_at: number }>();
    assert.equal(recognition?.reference_weight_at, 1793937548);
    assert.equal(
      Math.round(recognition!.reference_weight_kg * 1000) / 1000,
      71.209,
    );
  } finally {
    h.cleanup();
  }
});

test("naming a scale user assigns older readings with the same candidate", async () => {
  const h = await harness();
  try {
    await addReading(h.db, 1, [26954592], 1793937548);
    await addReading(h.db, 2, [26954592], 1793937600);
    await addReading(h.db, 3, [111], 1793937700);
    await addReading(h.db, 4, [26954592, 111], 1793937800);
    assert.equal(
      (
        await h.post("/readings/2/name-scale-user", {
          candidate_id: "26954592",
          name: "Sam",
          short_name: "SAM",
          height_cm: "181",
          age_years: "40",
          sex: "0",
          reference_weight_kg: "71.209",
        })
      ).status,
      303,
    );
    const assigned = await h.db
      .prepare("SELECT id,user_id FROM readings ORDER BY id")
      .all<{ id: number; user_id: number | null }>();
    assert.deepEqual(
      assigned.results.map((row) => ({ ...row })),
      [
        { id: 1, user_id: 26954592 },
        { id: 2, user_id: 26954592 },
        { id: 3, user_id: null },
        { id: 4, user_id: null },
      ],
    );
    const recognition = await h.db
      .prepare(
        "SELECT reference_weight_kg,reference_weight_at FROM users WHERE id=?",
      )
      .bind(26954592)
      .first<{ reference_weight_kg: number; reference_weight_at: number }>();
    assert.equal(recognition?.reference_weight_at, 1793937600);
    assert.equal(
      Math.round(recognition!.reference_weight_kg * 1000) / 1000,
      71.209,
    );
  } finally {
    h.cleanup();
  }
});

test("naming a scale user preserves memberships on other scales", async () => {
  const h = await harness();
  try {
    await h.db
      .prepare(
        "INSERT INTO scales(id,label,model,mac,secret,settings_ready,time_zone) VALUES(2,'Other','WBS06','020000000002','0123456789abcdef',1,'UTC')",
      )
      .run();
    await h.db
      .prepare(
        "INSERT INTO users(id,name,short_name,height_cm,age_years,sex,reference_weight_kg,created_at) VALUES(26954592,'Existing','EXT',170,40,0,70,1)",
      )
      .run();
    await h.db
      .prepare(
        "INSERT INTO scale_users(scale_id,user_id,rank) VALUES(2,26954592,0)",
      )
      .run();
    await addReading(h.db, 1, [26954592], 1793937548);
    assert.equal(
      (
        await h.post("/readings/1/name-scale-user", {
          candidate_id: "26954592",
          name: "Ignored",
          short_name: "IGN",
          height_cm: "181",
          age_years: "40",
          sex: "0",
          reference_weight_kg: "71.209",
        })
      ).status,
      303,
    );
    const memberships = await h.db
      .prepare(
        "SELECT scale_id FROM scale_users WHERE user_id=? ORDER BY scale_id",
      )
      .bind(26954592)
      .all<{ scale_id: number }>();
    assert.deepEqual(
      memberships.results.map((row) => row.scale_id),
      [1, 2],
    );
    const user = await h.db
      .prepare("SELECT name FROM users WHERE id=?")
      .bind(26954592)
      .first<{ name: string }>();
    assert.equal(user?.name, "Existing");
    const reading = await h.db
      .prepare("SELECT user_id FROM readings WHERE id=1")
      .first<{ user_id: number }>();
    assert.equal(reading?.user_id, 26954592);
  } finally {
    h.cleanup();
  }
});

test("naming rejects an unknown candidate and an already assigned reading", async () => {
  const h = await harness();
  try {
    await addReading(h.db, 1, [111], 1793937548);
    const invalid = await h.post("/readings/1/name-scale-user", {
      candidate_id: "222",
      name: "Sam",
      short_name: "SAM",
      height_cm: "181",
      age_years: "40",
      sex: "0",
      reference_weight_kg: "71.209",
    });
    assert.equal(invalid.status, 303);
    assert.match(
      decodeURIComponent(
        (invalid.headers.get("location") ?? "").replace(/\+/g, " "),
      ),
      /Choose a scale user from this reading/,
    );
    assert.equal(
      (
        await h.db.prepare("SELECT COUNT(*) AS count FROM users").first<{
          count: number;
        }>()
      )?.count,
      0,
    );

    assert.equal(
      (
        await h.post("/readings/1/name-scale-user", {
          candidate_id: "111",
          name: "Sam",
          short_name: "SAM",
          height_cm: "181",
          age_years: "40",
          sex: "0",
          reference_weight_kg: "71.209",
        })
      ).status,
      303,
    );
    const again = await h.post("/readings/1/name-scale-user", {
      candidate_id: "111",
      name: "Sam",
      short_name: "SAM",
      height_cm: "181",
      age_years: "40",
      sex: "0",
      reference_weight_kg: "71.209",
    });
    assert.equal(again.status, 303);
    assert.match(
      decodeURIComponent(
        (again.headers.get("location") ?? "").replace(/\+/g, " "),
      ),
      /already assigned/,
    );
  } finally {
    h.cleanup();
  }
});
