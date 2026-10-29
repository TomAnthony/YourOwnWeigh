/** Exercise household export/stage/merge/replace against a disposable local
 * Node or Wrangler instance, never a real household. Requires the synthetic
 * account created by check_bridge_integration.mjs and non-empty fixture data.
 * YOW_TEST_URL=http://127.0.0.1:8099 node tools/check_backup_integration.mjs
 * No access settings are restored; the current test password stays unchanged.
 */
import assert from "node:assert/strict";
const base = process.env.YOW_TEST_URL;
if (!base || new URL(base).hostname !== "127.0.0.1")
  throw new Error("Provide a disposable loopback fixture in YOW_TEST_URL");
let cookie = "",
  csrf = "";
async function request(path, data) {
  const headers = { Cookie: cookie, Origin: base };
  let body;
  if (data instanceof FormData) body = data;
  else if (data) {
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    body = new URLSearchParams({ ...data, _csrf: csrf });
  }
  const response = await fetch(base + path, {
    method: body ? "POST" : "GET",
    redirect: "manual",
    headers,
    body,
  });
  if (response.headers.has("set-cookie"))
    cookie = response.headers.get("set-cookie").split(";")[0];
  return response;
}
let html = await (await request("/login")).text();
csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(html)?.[1];
assert.ok(csrf);
assert.equal(
  (await request("/login", { password: "integration-test-only" })).status,
  303,
);
html = await (await request("/settings")).text();
csrf = /name="csrf-token" content="([a-f0-9]+)"/.exec(html)?.[1];
assert.ok(csrf);
const response = await request("/api/backup/export");
assert.equal(response.status, 200);
const original = await response.json();
assert.equal(original.format, "YOW-backup-v1");
assert.ok(
  original.sections.users.length &&
    original.sections.scales.length &&
    original.sections.readings.length,
  "Seed synthetic users, scales and readings first",
);
function canonical(value) {
  return Object.fromEntries(
    Object.entries(value.sections).map(([key, rows]) => [
      key,
      rows.map((r) => JSON.stringify(r)).sort(),
    ]),
  );
}
for (const mode of ["merge", "merge", "replace"]) {
  const form = new FormData();
  form.set("_csrf", csrf);
  form.set(
    "backup",
    new Blob([JSON.stringify(original)], { type: "application/json" }),
    "test.json",
  );
  const preview = await request("/api/backup/import", form);
  assert.equal(preview.status, 200);
  html = await preview.text();
  const id = /name="import_id" value="([^"]+)"/.exec(html)?.[1];
  const digest = /name="digest" value="([a-f0-9]+)"/.exec(html)?.[1];
  assert.ok(id && digest, "Expected a valid staged preview");
  const commit = await request("/api/backup/commit", {
    import_id: id,
    digest,
    mode,
    confirmed: "1",
  });
  assert.equal(commit.status, 303, await commit.text());
  const actual = await (await request("/api/backup/export")).json();
  assert.deepEqual(canonical(actual), canonical(original));
  assert.deepEqual(actual.accessSettings, original.accessSettings);
  // A submitted confirmation cannot be replayed after commit.
  html = await (
    await request("/api/backup/commit", {
      import_id: id,
      digest,
      mode,
      confirmed: "1",
    })
  ).text();
  assert.match(html, /expired/);
  console.log(
    `Backup ${mode}: atomic round-trip and expired-preview guard passed`,
  );
}
