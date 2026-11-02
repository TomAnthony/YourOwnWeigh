/** Portable household backups, with bounded staging and one atomic commit.
 * Table and column identifiers below are code constants, never file input.
 * Merge adds missing data; Replace is explicit. Authentication sessions and
 * bridge credentials are never exported or restored.
 */
import { bridgeHash } from "./bridge.ts";
import { firmwareVersion } from "./firmware_observation.ts";
import { validateStoredMetrics } from "./metrics.ts";
import { SCALE_MODELS } from "./models.ts";
type Row = Record<string, string | number | null>;
const columns: Record<string, string[]> = {
  settings: "key value".split(" "),
  users:
    "id name short_name height_cm age_years birth_date sex reference_weight_kg reference_weight_at active created_at".split(
      " ",
    ),
  scales:
    "id label model mac secret goff dst ngoff time_zone withings_capture ble_name ble_probe_identifier ble_hardware_version ble_bootloader_version ble_firmware_version ble_rescue_version ble_wifi_ssid ble_owner_host ble_owner_transport ble_captured_at firmware_version firmware_confirmed_at firmware_source feature_mask reported_feature_mask reported_feature_at reported_mfgid debug_mask beta_ws temp_code weight_code settings_ready roster_enabled roster_last_sent_at roster_snapshot screen_response summary_response weather_response last_session_at".split(
      " ",
    ),
  scale_users: "scale_id user_id rank".split(" "),
  readings:
    "id scale_id user_id attribution candidate_ids attribstatus meastime time_quality weight_value weight_unit measures_json group_json payload_hash first_received_at last_received_at attempts".split(
      " ",
    ),
  health_sync_receipts: "user_id reading_id synced_at".split(" "),
  reviewed_captures: "scale_id digest document captured_at".split(" "),
  events:
    "id scale_id event_type epoch user_id data_json payload_hash received_at attempts".split(
      " ",
    ),
  sync_audit: "id scale_id endpoint outcome received_at detail".split(" "),
  measure_attempts:
    "id scale_id received_at payload_sha256 form_without_session new_groups duplicate_groups".split(
      " ",
    ),
  measure_rejections:
    "id received_at validation_stage reason form_without_session".split(" "),
};
const sections = Object.keys(columns);
// Operational diagnostics can be regenerated and must never make a household
// backup too large to restore. Preserve empty sections for v1 compatibility.
const diagnostics = new Set([
  "sync_audit",
  "measure_attempts",
  "measure_rejections",
]);
const access = new Set([
  "admin_password",
  "api_password",
  "sync_password_mode",
]);
const preferences = new Set(["display_weight_unit", "next_local_user_id"]);
const now = () => Math.floor(Date.now() / 1000);
const MAX_BYTES = 10 * 1024 * 1024;
const MAX_ROWS = 25000;
export type Backup = {
  format: "YOW-backup-v1";
  schemaVersion: 1;
  exportedAt: string;
  sections: Record<string, Row[]>;
  accessSettings: Row[];
};

export async function exportBackup(db: D1Database): Promise<Backup> {
  const results = await db.batch(
    sections.map((table) =>
      db.prepare(
        `SELECT ${columns[table].join(",")} FROM ${table}${diagnostics.has(table) ? " LIMIT 0" : ""}`,
      ),
    ),
  );
  const rows = Object.fromEntries(
    sections.map((table, i) => [table, results[i].results as Row[]]),
  );
  const accessSettings = rows.settings.filter((r) => access.has(String(r.key)));
  rows.settings = rows.settings.filter((r) => preferences.has(String(r.key)));
  // Old experiments used this free-form field. Current settings and reviewed
  // captures have explicit sections; do not export an opaque vendor session.
  rows.scales = rows.scales.map((r) => ({ ...r, withings_capture: null }));
  return {
    format: "YOW-backup-v1",
    schemaVersion: 1,
    exportedAt: new Date().toISOString(),
    sections: rows,
    accessSettings,
  };
}
function integer(
  value: unknown,
  min = 0,
  max = Number.MAX_SAFE_INTEGER,
): value is number {
  return (
    Number.isSafeInteger(value) && Number(value) >= min && Number(value) <= max
  );
}
function parse(raw: string): Backup {
  if (new TextEncoder().encode(raw).length > MAX_BYTES)
    throw new Error("Backup exceeds 10 MiB");
  const b = JSON.parse(raw) as Backup;
  if (
    b.format !== "YOW-backup-v1" ||
    b.schemaVersion !== 1 ||
    !b.sections ||
    !Array.isArray(b.accessSettings)
  )
    throw new Error("Unsupported backup format");
  b.format = "YOW-backup-v1";
  if (Object.keys(b.sections).some((key) => !sections.includes(key)))
    throw new Error("Backup contains an unknown section");
  let count = 0;
  for (const section of sections) {
    const data = b.sections[section];
    if (!Array.isArray(data)) throw new Error(`Missing ${section} section`);
    // Older backups may contain many diagnostic rows. They are disposable and
    // never staged, so they cannot exhaust the household row budget on restore.
    if (diagnostics.has(section)) {
      b.sections[section] = [];
      continue;
    }
    count += data.length;
    for (const row of data) {
      if (
        section === "users" &&
        row &&
        typeof row === "object" &&
        !("reference_weight_at" in row)
      )
        row.reference_weight_at = null;
      // Backups from before firmware tracking remain importable. Use the export's
      // original observation time, never the time the backup is restored.
      if (
        section === "readings" &&
        row &&
        typeof row === "object" &&
        !("group_json" in row)
      )
        row.group_json = null;
      const fields = [
        "firmware_version",
        "firmware_confirmed_at",
        "firmware_source",
      ];
      if (
        section === "scales" &&
        row &&
        typeof row === "object" &&
        !Array.isArray(row) &&
        fields.every((key) => !(key in row))
      ) {
        const valid =
          firmwareVersion(row.ble_firmware_version) !== null &&
          integer(row.ble_captured_at, 1, now());
        row.firmware_version = valid ? row.ble_firmware_version : null;
        row.firmware_confirmed_at = valid ? row.ble_captured_at : null;
        row.firmware_source = valid ? "bluetooth" : null;
      }
      if (
        !row ||
        typeof row !== "object" ||
        Array.isArray(row) ||
        Object.keys(row).some((key) => !columns[section].includes(key)) ||
        columns[section].some((key) => !(key in row))
      )
        throw new Error(`Invalid ${section} columns`);
      if (
        Object.values(row).some(
          (value) =>
            value !== null &&
            typeof value !== "string" &&
            (typeof value !== "number" || !Number.isFinite(value)),
        )
      )
        throw new Error(`Invalid ${section} value`);
      if (JSON.stringify(row).length > 256000)
        throw new Error(`A ${section} row exceeds 256 KB`);
      if (
        section === "scales" &&
        !fields.every((key) => row[key] === null) &&
        (firmwareVersion(row.firmware_version) === null ||
          !integer(row.firmware_confirmed_at, 1, now() + 300) ||
          !["bluetooth", "wifi"].includes(String(row.firmware_source)))
      )
        throw new Error("Invalid firmware observation");
      if ("id" in row && !integer(row.id, 1))
        throw new Error(`Invalid ${section} ID`);
      if (
        "payload_hash" in row &&
        !/^[a-f0-9]{64}$/.test(String(row.payload_hash))
      )
        throw new Error(`Invalid ${section} digest`);
    }
  }
  if (count > MAX_ROWS) throw new Error("Backup exceeds 25,000 household rows");
  const ids = (table: string) =>
    new Set(b.sections[table].map((r) => Number(r.id)));
  const users = ids("users"),
    scales = ids("scales"),
    readings = ids("readings");
  for (const section of sections) {
    const rows = b.sections[section];
    if (
      columns[section].includes("id") &&
      new Set(rows.map((r) => r.id)).size !== rows.length
    )
      throw new Error(`Duplicate ${section} ID`);
    for (const r of rows) {
      if (
        "scale_id" in r &&
        r.scale_id !== null &&
        !scales.has(Number(r.scale_id))
      )
        throw new Error("Missing referenced scale");
      if (
        section !== "events" &&
        "user_id" in r &&
        r.user_id !== null &&
        !users.has(Number(r.user_id))
      )
        throw new Error("Missing referenced user");
      if ("reading_id" in r && !readings.has(Number(r.reading_id)))
        throw new Error("Missing referenced reading");
    }
  }
  const macs = new Set();
  for (const r of b.sections.scales) {
    if (
      !Object.hasOwn(SCALE_MODELS, String(r.model)) ||
      !/^[A-F0-9]{12}$/.test(String(r.mac)) ||
      macs.has(r.mac) ||
      typeof r.secret !== "string" ||
      !r.secret ||
      r.secret.length > 256
    )
      throw new Error("Invalid or duplicate scale identity");
    macs.add(r.mac);
    if (
      ![0, 1].includes(Number(r.settings_ready)) ||
      ![0, 1].includes(Number(r.roster_enabled))
    )
      throw new Error("Invalid scale delivery flags");
    for (const key of [
      "roster_snapshot",
      "screen_response",
      "summary_response",
      "weather_response",
    ])
      if (r[key] !== null) JSON.parse(String(r[key]));
    if (r.time_zone !== null)
      new Intl.DateTimeFormat("en", { timeZone: String(r.time_zone) }).format();
  }
  for (const r of b.sections.users)
    if (
      !integer(r.id, 1, 2147483647) ||
      !String(r.name) ||
      !/^[A-Za-z0-9]{1,3}$/.test(String(r.short_name)) ||
      ![0, 1].includes(Number(r.sex)) ||
      ![0, 1].includes(Number(r.active)) ||
      Number(r.height_cm) < 80 ||
      Number(r.height_cm) > 250 ||
      Number(r.reference_weight_kg) < 2 ||
      Number(r.reference_weight_kg) > 500 ||
      (r.reference_weight_at !== null &&
        !integer(r.reference_weight_at, 946684800, now()))
    )
      throw new Error("Invalid user profile");
  for (const r of b.sections.readings) {
    if (
      !(
        (r.weight_value === null && r.weight_unit === null) ||
        (integer(r.weight_value, 1) && integer(r.weight_unit, -12, 12))
      ) ||
      !["trusted", "untrusted"].includes(String(r.time_quality))
    )
      throw new Error("Invalid stored reading");
    validateStoredMetrics(r);
  }
  for (const r of b.sections.settings)
    if (!preferences.has(String(r.key)) || typeof r.value !== "string")
      throw new Error("Unknown preference");
  const seenAccess = new Set();
  for (const r of b.accessSettings) {
    if (
      !access.has(String(r.key)) ||
      typeof r.value !== "string" ||
      seenAccess.has(r.key)
    )
      throw new Error("Invalid access settings");
    seenAccess.add(r.key);
    if (
      String(r.key).endsWith("password") &&
      !/^pbkdf2_sha256\$(100000|[1-9][0-9]{5})\$[a-f0-9]{32}\$[a-f0-9]{64}$/.test(
        r.value,
      )
    )
      throw new Error("Invalid password hash");
    if (
      r.key === "sync_password_mode" &&
      !["shared", "separate"].includes(r.value)
    )
      throw new Error("Invalid Sync API password mode");
  }
  return b;
}
export async function stageBackup(
  db: D1Database,
  raw: string,
  adminId: string,
) {
  const data = parse(raw),
    id = crypto.randomUUID(),
    expires = now() + 900,
    digest = await bridgeHash(raw);
  await db
    .prepare("DELETE FROM backup_staging_rows WHERE expires_at<?")
    .bind(now())
    .run();
  const statements: D1PreparedStatement[] = [];
  for (const [section, rows] of Object.entries({
    ...data.sections,
    accessSettings: data.accessSettings,
  })) {
    for (let i = 0; i < rows.length; i += 100)
      statements.push(
        db
          .prepare(
            "INSERT INTO backup_staging_rows(import_id,section,row_number,row_json,expires_at) SELECT ?,?,CAST(key AS INTEGER)+?,value,? FROM json_each(?)",
          )
          .bind(
            id,
            section,
            i,
            expires,
            JSON.stringify(rows.slice(i, i + 100)),
          ),
      );
  }
  statements.push(
    db
      .prepare("INSERT INTO backup_staging_rows VALUES(?, '__meta__',0,?,?)")
      .bind(
        id,
        JSON.stringify({
          adminId,
          digest,
          counts: Object.fromEntries(
            sections.map((s) => [s, data.sections[s].length]),
          ),
        }),
        expires,
      ),
  );
  try {
    for (let i = 0; i < statements.length; i += 10)
      await db.batch(statements.slice(i, i + 10));
  } catch (error) {
    await db
      .prepare("DELETE FROM backup_staging_rows WHERE import_id=?")
      .bind(id)
      .run();
    throw error;
  }
  return {
    id,
    digest,
    counts: Object.fromEntries(
      sections.map((s) => [s, data.sections[s].length]),
    ),
    hasAccess: data.accessSettings.some((r) => r.key === "admin_password"),
  };
}
export async function commitBackup(
  db: D1Database,
  id: string,
  digest: string,
  adminId: string,
  mode: "merge" | "replace",
  restoreAccess: boolean,
) {
  if (!["merge", "replace"].includes(mode))
    throw new Error("Unknown restore mode");
  const meta = await db
    .prepare(
      "SELECT row_json FROM backup_staging_rows WHERE import_id=? AND section='__meta__' AND expires_at>?",
    )
    .bind(id, now())
    .first<{ row_json: string }>();
  if (!meta) throw new Error("Backup preview expired; upload it again");
  const parsed = JSON.parse(meta.row_json);
  if (parsed.adminId !== adminId || parsed.digest !== digest)
    throw new Error("Backup confirmation does not match this preview");
  if (
    restoreAccess &&
    !(await db
      .prepare(
        "SELECT 1 FROM backup_staging_rows WHERE import_id=? AND section='accessSettings' AND json_extract(row_json,'$.key')='admin_password'",
      )
      .bind(id)
      .first())
  )
    throw new Error("Backup has no admin password to restore");
  const conflict = await db
    .prepare(
      "SELECT 1 FROM backup_staging_rows s JOIN scales d ON d.mac=json_extract(s.row_json,'$.mac') WHERE s.import_id=? AND s.section='scales' AND (d.model<>json_extract(s.row_json,'$.model') OR d.secret<>json_extract(s.row_json,'$.secret')) LIMIT 1",
    )
    .bind(id)
    .first();
  if (mode === "merge" && conflict)
    throw new Error(
      "A scale MAC has a different model or secret; resolve it before merging",
    );
  const statements: D1PreparedStatement[] = [
    db
      .prepare(
        "INSERT INTO backup_staging_rows(import_id,section,row_number,row_json,expires_at) VALUES(?, '__guard__',0, CASE WHEN EXISTS(SELECT 1 FROM backup_staging_rows WHERE import_id=? AND section='__meta__' AND expires_at>? AND json_extract(row_json,'$.adminId')=? AND json_extract(row_json,'$.digest')=?) THEN '{}' ELSE '' END,?)",
      )
      .bind(id, id, now(), adminId, digest, now() + 900),
  ];
  if (mode === "merge")
    statements.push(
      db
        .prepare(
          "UPDATE backup_staging_rows SET row_json=CASE WHEN EXISTS(SELECT 1 FROM backup_staging_rows s JOIN scales d ON d.mac=json_extract(s.row_json,'$.mac') WHERE s.import_id=? AND s.section='scales' AND (d.model<>json_extract(s.row_json,'$.model') OR d.secret<>json_extract(s.row_json,'$.secret'))) THEN '' ELSE row_json END WHERE import_id=? AND section='__guard__'",
        )
        .bind(id, id),
    );
  if (mode === "replace") {
    for (const table of [
      "device_sessions",
      "auth_failures",
      "challenges",
      "health_sync_receipts",
      "scale_users",
      "readings",
      "reviewed_captures",
      "events",
      "sync_audit",
      "measure_attempts",
      "measure_rejections",
      "scales",
      "users",
    ])
      statements.push(db.prepare(`DELETE FROM ${table}`));
    statements.push(
      db.prepare("DELETE FROM settings WHERE key='display_weight_unit'"),
    );
  }
  // Rows refer to source IDs; resolve them inside the same final transaction.
  const v = (key: string) => `json_extract(s.row_json,'$.${key}')`;
  const source = (section: string, key: string, idExpression: string) =>
    `(SELECT json_extract(x.row_json,'$.${key}') FROM backup_staging_rows x WHERE x.import_id=s.import_id AND x.section='${section}' AND json_extract(x.row_json,'$.id')=${idExpression})`;
  const scale = (expr: string) =>
    `(SELECT id FROM scales WHERE mac=${source("scales", "mac", expr)})`;
  const reading = (expr: string) =>
    `(SELECT id FROM readings WHERE payload_hash=${source("readings", "payload_hash", expr)})`;
  for (const table of sections) {
    let cols = columns[table].filter(
      (c) => mode === "replace" || c !== "id" || table === "users",
    );
    const expr = cols.map((c) =>
      c === "scale_id"
        ? scale(v(c))
        : c === "reading_id"
          ? reading(v(c))
          : v(c),
    );
    const where = ["s.import_id=?", `s.section='${table}'`];
    // Audit rows have no semantic unique index. Compare their canonical content,
    // excluding local IDs, after resolving scale references.
    if (
      mode === "merge" &&
      ["sync_audit", "measure_attempts", "measure_rejections"].includes(table)
    )
      where.push(
        `NOT EXISTS(SELECT 1 FROM ${table} d WHERE ${cols.map((c, i) => `d.${c} IS ${expr[i]}`).join(" AND ")})`,
      );
    const conflictTarget = (
      {
        settings: "key",
        users: "id",
        scales: "mac",
        scale_users: "scale_id,user_id",
        readings: "payload_hash",
        health_sync_receipts: "user_id,reading_id",
        reviewed_captures: "scale_id",
        events: "payload_hash",
      } as Record<string, string>
    )[table];
    const onConflict = conflictTarget
      ? ` ON CONFLICT(${conflictTarget}) DO NOTHING`
      : "";
    statements.push(
      db
        .prepare(
          `INSERT INTO ${table}(${cols.join(",")}) SELECT ${expr.join(",")} FROM backup_staging_rows s WHERE ${where.join(" AND ")}${onConflict}`,
        )
        .bind(id),
    );
  }
  if (restoreAccess) {
    statements.push(
      db.prepare(
        "DELETE FROM settings WHERE key IN ('admin_password','api_password','sync_password_mode')",
      ),
    );
    statements.push(
      db
        .prepare(
          "INSERT INTO settings(key,value) SELECT json_extract(row_json,'$.key'),json_extract(row_json,'$.value') FROM backup_staging_rows WHERE import_id=? AND section='accessSettings'",
        )
        .bind(id),
    );
    statements.push(
      db.prepare(
        "UPDATE settings SET value=CAST(value AS INTEGER)+1 WHERE key='auth_version'",
      ),
    );
    statements.push(db.prepare("DELETE FROM admin_sessions"));
  }
  statements.push(
    db.prepare("DELETE FROM backup_staging_rows WHERE import_id=?").bind(id),
  );
  await db.batch(statements);
  return { imported: true, mode, restoreAccess };
}
