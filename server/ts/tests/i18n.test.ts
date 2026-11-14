import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LocalSqlite } from "../sqlite.ts";
import { handleApp, type AppEnv } from "../app.ts";
import { exportBackup } from "../backup.ts";
import {
  LANGUAGES,
  MESSAGE_KEYS,
  browserLanguage,
  resolveLanguage,
  translator,
} from "../i18n.ts";
import { timeLabel, weightLabel } from "../ui.ts";

test("Accept-Language picks the best supported language", () => {
  assert.equal(browserLanguage("de-DE,de;q=0.9,en;q=0.8"), "de");
  assert.equal(browserLanguage("fr-FR,fr;q=0.9,de;q=0.5,en;q=0.7"), "en");
  assert.equal(browserLanguage("en;q=0.2, DE-at"), "de");
  assert.equal(browserLanguage("de;q=0,en"), "en");
  assert.equal(browserLanguage("fr, it"), null);
  assert.equal(browserLanguage(null), null);
  assert.equal(resolveLanguage(null, "de"), "de");
  assert.equal(resolveLanguage("auto", "fr"), "en");
  assert.equal(resolveLanguage("en", "de"), "en");
  assert.equal(resolveLanguage("de", "en"), "de");
  assert.equal(resolveLanguage("xx", "de"), "de");
});

test("every catalog matches the English placeholders", () => {
  const en = translator("en");
  const placeholders = (text: string) =>
    [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
  for (const language of LANGUAGES) {
    const t = translator(language);
    for (const key of MESSAGE_KEYS) {
      assert.ok(t(key).trim(), `${language}:${key} is empty`);
      assert.deepEqual(
        placeholders(t(key)),
        placeholders(en(key)),
        `${language}:${key} placeholders`,
      );
    }
  }
  assert.equal(
    translator("de")("reading.position", { position: 2 }),
    "Position 2",
  );
});

test("dates and weights follow the display language", () => {
  const row = { weight_value: 70300, weight_unit: -3 };
  assert.equal(weightLabel(row, "kg"), "70.30 kg");
  assert.equal(weightLabel(row, "kg", "de"), "70,30 kg");
  assert.equal(weightLabel(row, "lb", "de"), "155,0 lb");
  assert.equal(
    weightLabel({ weight_value: 1234567, weight_unit: -3 }, "kg"),
    "1234.57 kg",
  );
  assert.match(timeLabel(1793000000, "de"), /^\d\d\.\d\d\.2026, \d\d:\d\d$/);
  assert.equal(timeLabel(0, "de"), "Unbekannt");
});

test("dashboard and settings follow the browser or the saved language", async () => {
  const directory = mkdtempSync(join(tmpdir(), "yow-i18n-test-"));
  const store = new LocalSqlite(join(directory, "test.sqlite3"));
  const env: AppEnv = {
    DB: store.asD1(),
    YOW_BOOTSTRAP_TOKEN: "dummy-test-bootstrap-token",
  };
  let cookie = "";
  let csrf = "";
  const request = (
    path: string,
    acceptLanguage = "",
    method = "GET",
    fields?: Record<string, string>,
  ) => {
    const headers: Record<string, string> = {};
    if (cookie) headers.Cookie = cookie;
    if (acceptLanguage) headers["Accept-Language"] = acceptLanguage;
    if (fields) headers["Content-Type"] = "application/x-www-form-urlencoded";
    return handleApp(
      new Request(`https://local.test${path}`, {
        method,
        headers,
        body: fields
          ? new URLSearchParams({ _csrf: csrf, ...fields }).toString()
          : undefined,
      }),
      env,
    );
  };
  try {
    const first = await request("/setup");
    cookie = first.headers.get("set-cookie")!.split(";")[0];
    csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(await first.text())![1];
    const setup = await request("/setup", "", "POST", {
      bootstrap_token: "dummy-test-bootstrap-token",
      password: "password-123",
      confirm: "password-123",
    });
    assert.equal(setup.status, 303);
    cookie = setup.headers.get("set-cookie")!.split(";")[0];

    const english = await (await request("/")).text();
    csrf = /name="_csrf" value="([a-f0-9]+)"/.exec(english)![1];
    assert.match(english, /<html lang="en">/);
    assert.match(english, />Readings</);
    assert.match(english, /No users have been added yet\./);

    const german = await (await request("/", "de-DE,de;q=0.9")).text();
    assert.match(german, /<html lang="de">/);
    assert.match(german, /<title>Dashboard · YourOwnWeigh<\/title>/);
    assert.match(german, />Messungen</);
    assert.match(german, />Abmelden</);
    assert.match(german, /Es wurden noch keine Personen angelegt\./);

    const settings = await (await request("/settings", "de")).text();
    assert.match(settings, /<h2>Anzeige<\/h2>/);
    assert.match(
      settings,
      /<option value="auto" selected>Browser-Standard<\/option>/,
    );
    assert.match(settings, /<option value="de">Deutsch<\/option>/);

    const saved = await request("/preferences", "en", "POST", {
      weight_unit: "kg",
      language: "de",
    });
    assert.equal(saved.status, 303);
    assert.equal(
      new URL(
        saved.headers.get("location") ?? "",
        "https://local.test",
      ).searchParams.get("notice"),
      "Anzeigeeinstellungen gespeichert",
    );
    assert.match(await (await request("/", "en")).text(), /<html lang="de">/);

    const keepsLanguage = await request("/preferences", "en", "POST", {
      weight_unit: "lb",
    });
    assert.equal(keepsLanguage.status, 303);
    assert.match(await (await request("/", "en")).text(), /<html lang="de">/);

    const invalid = await request("/preferences", "en", "POST", {
      weight_unit: "kg",
      language: "fr",
    });
    assert.equal(
      new URL(
        invalid.headers.get("location") ?? "",
        "https://local.test",
      ).searchParams.get("notice"),
      "Invalid display language",
    );
    assert.match(await (await request("/", "en")).text(), /<html lang="de">/);

    const backup = await exportBackup(env.DB);
    assert.equal(
      backup.sections.settings.find((r) => r.key === "display_language")?.value,
      "de",
    );
  } finally {
    store.close();
    rmSync(directory, { recursive: true, force: true });
  }
});
