/** One HTTP application for Cloudflare Workers and the local Node listener. */
import { namedMetrics, observedMetrics, storedMeasures } from "./metrics.ts";
import { refreshRecognitionWeight } from "./recognition.ts";
import { exportBackup, stageBackup, commitBackup } from "./backup.ts";
import {
  firmwareObservation,
  firmwareVersion,
} from "./firmware_observation.ts";
import {
  firmwareWorkspace,
  scalesWorkspace,
  settingsWorkspace,
  syncPage,
} from "./integrated_ui.ts";
import { handleScaleRequest, zoneTriplet, roster } from "./scale_api.ts";
import {
  dashboardPage,
  escapeHtml,
  layout,
  loginPage,
  readingsPage,
  setupPage,
  userReadingsPage,
  usersPage,
} from "./ui.ts";

type Row = Record<string, any>;
type Value = string | number | null;
export interface AppEnv {
  bridgeRequest?: (
    request: Request,
    adminId: string | null,
  ) => Promise<Response>;
  DB: D1Database;
  ASSETS?: { fetch(request: Request): Promise<Response> };
  ALLOW_HTTP_SCALE?: boolean;
  YOW_BOOTSTRAP_TOKEN?: string;
  captureWithings?: (scale: Row) => Promise<string>;
  lookupFirmwareOffer?: (identity: Row) => Promise<Row>;
}
const SCALE_PATHS = new Set([
  "/once",
  "/session",
  "/measure",
  "/v2/screen",
  "/v2/summary",
  "/v2/weather",
  "/v2/event",
  "/v2/measure",
  "/v2/feature",
]);
const SESSION_COOKIE = "yow_session";
const MAC = /^(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}$|^[0-9a-f]{12}$/i;
const SHORT = /^[A-Za-z0-9]{1,3}$/;
const utf8 = new TextEncoder();
const now = () => Math.floor(Date.now() / 1000);
const randomHex = (bytes: number) =>
  Array.from(crypto.getRandomValues(new Uint8Array(bytes)), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
const hex = (bytes: Uint8Array) =>
  Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
async function digest(value: string): Promise<string> {
  return hex(
    new Uint8Array(await crypto.subtle.digest("SHA-256", utf8.encode(value))),
  );
}
function equal(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let difference = 0;
  for (let i = 0; i < a.length; i++)
    difference |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return difference === 0;
}
async function pbkdf2(
  password: string,
  salt: Uint8Array<ArrayBuffer>,
  iterations: number,
): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    utf8.encode(password),
    "PBKDF2",
    false,
    ["deriveBits"],
  );
  return hex(
    new Uint8Array(
      await crypto.subtle.deriveBits(
        { name: "PBKDF2", hash: "SHA-256", salt, iterations },
        key,
        256,
      ),
    ),
  );
}
async function passwordHash(password: string): Promise<string> {
  if (password.length < 8 || password.length > 1024)
    throw new Error("Password must contain 8 to 1024 characters");
  const salt = crypto.getRandomValues(new Uint8Array(16));
  // Workers WebCrypto caps PBKDF2 at 100,000 iterations. Use the same
  // password-hash format in both Node and Worker deployments.
  return `pbkdf2_sha256$100000$${hex(salt)}$${await pbkdf2(password, salt, 100000)}`;
}
async function passwordMatches(
  password: string,
  encoded: string | null,
): Promise<boolean> {
  if (!encoded || password.length > 1024) return false;
  const [algorithm, count, salt, expected] = encoded.split("$");
  const iterations = Number(count);
  if (
    algorithm !== "pbkdf2_sha256" ||
    !Number.isInteger(iterations) ||
    iterations < 100000 ||
    iterations > 1000000 ||
    !/^[0-9a-f]{32}$/i.test(salt) ||
    !/^[0-9a-f]{64}$/i.test(expected)
  )
    return false;
  const bytes = Uint8Array.from(salt.match(/../g)!, (part) =>
    parseInt(part, 16),
  );
  return equal(
    await pbkdf2(password, bytes, iterations),
    expected.toLowerCase(),
  );
}
async function one<T extends Row>(
  db: D1Database,
  sql: string,
  ...args: Value[]
): Promise<T | null> {
  return db
    .prepare(sql)
    .bind(...args)
    .first<T>();
}
async function rows<T extends Row>(
  db: D1Database,
  sql: string,
  ...args: Value[]
): Promise<T[]> {
  return (
    await db
      .prepare(sql)
      .bind(...args)
      .all<T>()
  ).results;
}
async function run(
  db: D1Database,
  sql: string,
  ...args: Value[]
): Promise<D1Result> {
  return db
    .prepare(sql)
    .bind(...args)
    .run();
}
async function setting(db: D1Database, key: string): Promise<string | null> {
  return (
    (
      await one<{ value: string }>(
        db,
        "SELECT value FROM settings WHERE key=?",
        key,
      )
    )?.value ?? null
  );
}
const saveSetting = (db: D1Database, key: string, value: string) =>
  db
    .prepare(
      "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
    )
    .bind(key, value);
function html(body: string, status = 200, cookie?: string): Response {
  const headers = new Headers({
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy":
      "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'",
  });
  if (cookie) headers.set("Set-Cookie", cookie);
  return new Response(body, { status, headers });
}
function json(body: unknown, status = 200): Response {
  return Response.json(body, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
function redirect(path: string, notice = "", cookie?: string): Response {
  const url = new URL(path, "https://local.invalid");
  if (notice) url.searchParams.set("notice", notice.slice(0, 250));
  const headers = new Headers({
    Location: url.pathname + url.search + url.hash,
    "Cache-Control": "no-store",
  });
  if (cookie) headers.set("Set-Cookie", cookie);
  return new Response(null, { status: 303, headers });
}
function cookieValue(request: Request): string | null {
  return (
    /(?:^|;\s*)yow_session=([a-f0-9]{64})(?:;|$)/.exec(
      request.headers.get("Cookie") ?? "",
    )?.[1] ?? null
  );
}
type BrowserSession = {
  token_hash: string;
  csrf: string;
  is_admin: number;
  auth_version: number;
  expires_at: number;
};
async function browserSession(
  db: D1Database,
  request: Request,
): Promise<{ row: BrowserSession; cookie?: string }> {
  const token = cookieValue(request);
  if (token) {
    const found = await one<BrowserSession>(
      db,
      "SELECT * FROM admin_sessions WHERE token_hash=? AND expires_at>?",
      await digest(token),
      now(),
    );
    if (found) return { row: found };
  }
  const fresh = randomHex(32);
  const row = {
    token_hash: await digest(fresh),
    csrf: randomHex(24),
    is_admin: 0,
    auth_version: 0,
    expires_at: now() + 86400,
  };
  await db.batch([
    db.prepare("DELETE FROM admin_sessions WHERE expires_at<=?").bind(now()),
    db
      .prepare(
        "INSERT INTO admin_sessions(token_hash,csrf,is_admin,auth_version,expires_at) VALUES(?,?,?,?,?)",
      )
      .bind(
        row.token_hash,
        row.csrf,
        row.is_admin,
        row.auth_version,
        row.expires_at,
      ),
  ]);
  return {
    row,
    cookie: `${SESSION_COOKIE}=${fresh}; HttpOnly; ${new URL(request.url).protocol === "https:" ? "Secure; " : ""}SameSite=Strict; Path=/; Max-Age=86400`,
  };
}
async function authenticated(
  db: D1Database,
  session: BrowserSession,
): Promise<boolean> {
  return (
    session.is_admin === 1 &&
    session.auth_version === Number((await setting(db, "auth_version")) ?? "0")
  );
}
async function rotateSession(
  db: D1Database,
  old: BrowserSession,
  admin: boolean,
  secure: boolean,
): Promise<string> {
  const token = randomHex(32);
  const authVersion = admin
    ? Number((await setting(db, "auth_version")) ?? "0")
    : 0;
  await db.batch([
    db
      .prepare("DELETE FROM admin_sessions WHERE token_hash=?")
      .bind(old.token_hash),
    db
      .prepare(
        "INSERT INTO admin_sessions(token_hash,csrf,is_admin,auth_version,expires_at) VALUES(?,?,?,?,?)",
      )
      .bind(
        await digest(token),
        randomHex(24),
        admin ? 1 : 0,
        authVersion,
        now() + 7 * 86400,
      ),
  ]);
  return `${SESSION_COOKIE}=${token}; HttpOnly; ${secure ? "Secure; " : ""}SameSite=Strict; Path=/; Max-Age=${7 * 86400}`;
}
function formText(form: FormData, key: string): string {
  const value = form.get(key);
  return typeof value === "string" ? value : "";
}
function formInteger(form: FormData, key: string, fallback?: number): number {
  const raw = formText(form, key);
  const value = raw === "" && fallback !== undefined ? fallback : Number(raw);
  if (!Number.isSafeInteger(value)) throw new Error(`Invalid ${key}`);
  return value;
}
function formNumber(form: FormData, key: string): number {
  const value = Number(formText(form, key));
  if (!Number.isFinite(value)) throw new Error(`Invalid ${key}`);
  return value;
}
function canonicalMac(value: string): string {
  if (!MAC.test(value.trim())) throw new Error("Invalid MAC address");
  return value.replace(/[:-]/g, "").toUpperCase();
}
function parseJson(value: string): any {
  return JSON.parse(value);
}
function dateAge(value: string): number {
  const date = new Date(`${value}T00:00:00Z`);
  if (
    !/^\d{4}-\d{2}-\d{2}$/.test(value) ||
    !Number.isFinite(date.valueOf()) ||
    date.toISOString().slice(0, 10) !== value ||
    date.valueOf() > Date.now()
  ) {
    throw new Error("Invalid birth date");
  }
  return (
    Math.round(((Date.now() - date.valueOf()) / 86400000 / 365.2425) * 10) / 10
  );
}
const readingOrder =
  "CASE WHEN r.time_quality='trusted' THEN r.meastime ELSE r.first_received_at END DESC,r.id DESC";
function exactWeight(value: number, unit: number): string {
  if (
    !Number.isSafeInteger(value) ||
    !Number.isInteger(unit) ||
    unit < -12 ||
    unit > 12
  )
    throw new Error("Invalid stored weight");
  const sign = value < 0 ? "-" : "";
  const digits = String(Math.abs(value));
  if (unit >= 0) return sign + digits + "0".repeat(unit);
  const place = digits.length + unit;
  return (
    sign +
    (place > 0
      ? `${digits.slice(0, place)}.${digits.slice(place)}`
      : `0.${"0".repeat(-place)}${digits}`)
  );
}
function safeError(error: unknown): string {
  return error instanceof Error
    ? error.message.slice(0, 180)
    : "Request failed";
}

async function activeMembers(db: D1Database, scaleId: number): Promise<Row[]> {
  return rows(
    db,
    "SELECT u.* FROM scale_users su JOIN users u ON u.id=su.user_id WHERE su.scale_id=? AND u.active=1 ORDER BY su.rank,u.id",
    scaleId,
  );
}
function safeRoster(scale: Row, users: Row[]): void {
  if (!scale.roster_snapshot || users.length < 1)
    throw new Error("Roster baseline or users missing");
  const baseline = parseJson(scale.roster_snapshot);
  if (
    !Array.isArray(baseline) ||
    new Set(baseline.map((item: Row) => item.id)).size !== baseline.length
  )
    throw new Error("Invalid roster baseline");
  for (const user of users)
    if (!baseline.some((item: Row) => item.id === user.id))
      throw new Error("User absent from roster baseline");
}
function validatedFixture(raw: string, endpoint: string): string | null {
  if (!raw.trim()) return null;
  const parsed = parseJson(raw);
  if (
    !parsed ||
    typeof parsed !== "object" ||
    parsed.status !== 0 ||
    !("body" in parsed)
  )
    throw new Error("Fixture must have status 0 and body");
  if (endpoint === "summary") {
    if (!Array.isArray(parsed.body))
      throw new Error("Summary body must be an array");
    for (const item of parsed.body) {
      const day = item?.t36?.d;
      if (
        day !== undefined &&
        (typeof day !== "string" || !/^\d{4}-\d{1,2}-\d{1,2}$/.test(day))
      )
        throw new Error("Invalid summary date");
    }
  }
  if (
    endpoint === "weather" &&
    (!Array.isArray(parsed.body?.series) || parsed.body.series.length > 8)
  )
    throw new Error("Invalid weather series");
  const compact = JSON.stringify(parsed);
  if (utf8.encode(compact).length > 16000)
    throw new Error("Fixture exceeds 16 KB");
  return compact;
}
function validatedRoster(raw: string): string | null {
  if (!raw.trim()) return null;
  const parsed = parseJson(raw);
  const required = [
    "id",
    "sn",
    "ht",
    "agt",
    "sx",
    "wt",
    "cr",
    "fm",
    "att",
    "cs",
    "ptf",
    "bd",
  ];
  if (
    !Array.isArray(parsed) ||
    parsed.length < 1 ||
    parsed.length > 8 ||
    new Set(parsed.map((item: Row) => item.id)).size !== parsed.length
  )
    throw new Error("Invalid roster baseline");
  for (const item of parsed) {
    if (
      !item ||
      typeof item !== "object" ||
      required.some((key) => !(key in item)) ||
      !Number.isInteger(item.id) ||
      item.id < 1 ||
      item.id > 2147483647 ||
      typeof item.cs !== "string" ||
      utf8.encode(item.cs).length >= 32
    )
      throw new Error("Invalid roster record");
  }
  return JSON.stringify(parsed);
}

function parseDeviceRecord(raw: string): Row {
  if (utf8.encode(raw).length < 1 || utf8.encode(raw).length > 4096)
    throw new Error("Device record must be at most 4 KB");
  const record = parseJson(raw);
  const isBody =
    record.format === "YOW-BLE-device-v1" &&
    record.model === "WBS06" &&
    record.name === "Body";
  const isWS30 =
    record.format === "YOW-Classic-device-v1" &&
    record.model === "WBS03" &&
    typeof record.name === "string" &&
    /WS-?30/i.test(record.name);
  const isBodySmart =
    record.format === "YOW-BLE-device-v1" &&
    record.model === "WBS13" &&
    record.name === "Body Smart";
  const isBodyCardio =
    record.format === "YOW-BLE-device-v1" &&
    record.model === "WBS04" &&
    record.name === "Body Cardio";
  if (!isBody && !isWS30 && !isBodySmart && !isBodyCardio)
    throw new Error("Unsupported device enrollment record");
  record.mac = canonicalMac(record.mac);
  if (!/^[a-f0-9]{16}$/i.test(record.session_secret ?? ""))
    throw new Error("Invalid device secret");
  for (const key of [
    "hardware_version",
    "bootloader_version",
    "firmware_version",
    "rescue_version",
    "captured_at",
  ]) {
    if (
      !Number.isInteger(record[key]) ||
      record[key] < 0 ||
      record[key] > 0xffffffff
    )
      throw new Error(`Invalid device ${key}`);
  }
  if (record.captured_at < 1 || record.captured_at > now() + 300)
    throw new Error("Invalid device capture time");
  if (
    isBody &&
    (record.hardware_version !== 0xffffff ||
      record.bootloader_version !== 4 ||
      ![1181, 123, 124, 125, 126, 127].includes(record.firmware_version))
  ) {
    throw new Error("BLE identity is outside the reviewed WBS06 profile");
  }
  if (
    isBodySmart &&
    (record.hardware_version !== 0xffffff ||
      record.bootloader_version !== 2 ||
      record.firmware_version !== 100)
  )
    throw new Error("BLE identity is outside the reviewed WBS13 profile");
  if (
    isBodyCardio &&
    (record.hardware_version !== 0xffffff ||
      record.bootloader_version !== 12 ||
      ![2231, 100, 101, 102].includes(record.firmware_version))
  )
    throw new Error("BLE identity is outside the reviewed WBS04 profile");
  if (
    isWS30 &&
    (record.bootloader_version !== 15 ||
      ![921, 100, 101, 102].includes(record.firmware_version))
  ) {
    throw new Error("Classic identity is outside the reviewed WS-30 profile");
  }
  if (
    record.wifi_ssid != null &&
    (typeof record.wifi_ssid !== "string" ||
      utf8.encode(record.wifi_ssid).length > 32)
  )
    throw new Error("Invalid Wi‑Fi SSID");
  if (record.owner_host != null) {
    if (
      typeof record.owner_host !== "string" ||
      !new RegExp(
        `^[a-z0-9.-]{1,${isBodySmart ? 48 : isWS30 ? 59 : 63}}$`,
        isWS30 ? "" : "i",
      ).test(record.owner_host) ||
      (isWS30
        ? record.owner_transport !== "http" ||
          ![100, 101, 102].includes(record.firmware_version)
        : !["http", "https"].includes(record.owner_transport))
    )
      throw new Error("Invalid owner target");
  } else if (record.owner_transport != null)
    throw new Error("Owner transport requires a host");
  return record;
}

type Capture = {
  format: string;
  mac: string;
  ctp?: Row;
  ind?: Row;
  sp?: { users: Row[] };
  screen_response?: Row;
  summary_response?: Row;
  weather_response?: Row;
};
function parseCapture(raw: string): Capture {
  if (utf8.encode(raw).length > 128000)
    throw new Error("Capture exceeds 128 KB");
  const capture = parseJson(raw) as Capture;
  if (!capture || capture.format !== "WBS06-Withings-readonly-baseline-v1")
    throw new Error("Unexpected capture format");
  capture.mac = canonicalMac(capture.mac);
  if (
    !capture.sp ||
    !Array.isArray(capture.sp.users) ||
    capture.sp.users.length < 1 ||
    capture.sp.users.length > 8
  )
    throw new Error("Capture has no valid roster");
  const ids = new Set<number>();
  for (const user of capture.sp.users) {
    if (
      !Number.isInteger(user.id) ||
      user.id < 1 ||
      user.id > 2147483647 ||
      ids.has(user.id) ||
      typeof user.sn !== "string" ||
      !SHORT.test(user.sn) ||
      ![0, 1].includes(user.sx) ||
      ![user.ht, user.agt, user.wt].every(
        (value) => typeof value === "number" && Number.isFinite(value),
      ) ||
      user.ht < 0.8 ||
      user.ht > 2.5 ||
      user.agt < 1 ||
      user.agt > 120 ||
      user.wt < 2 ||
      user.wt > 500
    ) {
      throw new Error("Capture contains an invalid user");
    }
    ids.add(user.id);
  }
  return capture;
}
async function reviewedCapture(
  db: D1Database,
  scaleId: number,
): Promise<{ digest: string; capture: Capture } | null> {
  const row = await one<{ digest: string; document: string }>(
    db,
    "SELECT digest,document FROM reviewed_captures WHERE scale_id=?",
    scaleId,
  );
  if (!row) return null;
  const capture = parseCapture(row.document);
  return { digest: row.digest, capture };
}
async function stageCapture(
  db: D1Database,
  scaleId: number,
  raw: string,
): Promise<void> {
  const scale = await one(db, "SELECT id,mac FROM scales WHERE id=?", scaleId);
  if (!scale) throw new Error("Choose a known scale");
  const capture = parseCapture(raw);
  if (capture.mac !== scale.mac)
    throw new Error("Capture belongs to a different scale");
  await run(
    db,
    "INSERT INTO reviewed_captures(scale_id,digest,document,captured_at) VALUES(?,?,?,?) ON CONFLICT(scale_id) DO UPDATE SET digest=excluded.digest,document=excluded.document,captured_at=excluded.captured_at",
    scale.id,
    await digest(raw),
    raw,
    now(),
  );
}
async function importCaptureUsers(
  db: D1Database,
  scale: Row,
  stored: { digest: string; capture: Capture },
  importSettings: boolean,
  timeZone: string | null,
  selected?: Set<number>,
): Promise<void> {
  const roster = stored.capture.sp!.users;
  const existing = await rows(db, "SELECT id,name,short_name,sex FROM users");
  const byId = new Map(existing.map((u) => [u.id, u]));
  const old = scale.roster_snapshot ? parseJson(scale.roster_snapshot) : [];
  if (!Array.isArray(old)) throw new Error("Saved roster is malformed");
  const currentIds = new Set(roster.map((u) => u.id));
  if (old.some((u: Row) => !currentIds.has(u.id)))
    throw new Error("Capture removes existing roster users; review separately");
  const statements: D1PreparedStatement[] = [
    db
      .prepare(
        "UPDATE scales SET roster_snapshot=?,roster_enabled=0 WHERE id=?",
      )
      .bind(JSON.stringify(roster), scale.id),
  ];
  for (const [index, user] of roster.entries()) {
    const prior = byId.get(user.id);
    if (!prior && selected && !selected.has(user.id)) continue;
    if (!prior)
      statements.push(
        db
          .prepare(
            "INSERT INTO users(id,name,short_name,height_cm,age_years,sex,reference_weight_kg,created_at) VALUES(?,?,?,?,?,?,?,?)",
          )
          .bind(
            user.id,
            String(user.fn || user.sn)
              .trim()
              .slice(0, 100),
            user.sn,
            Math.round(user.ht * 100),
            user.agt,
            user.sx,
            user.wt,
            now(),
          ),
      );
    statements.push(
      db
        .prepare(
          "INSERT OR IGNORE INTO scale_users(scale_id,user_id,rank) VALUES(?,?,?)",
        )
        .bind(scale.id, user.id, index + 1),
    );
  }
  if (importSettings && scale.model === "WBS06") {
    if (
      scale.settings_ready ||
      scale.screen_response ||
      scale.summary_response ||
      scale.roster_enabled
    ) {
      throw new Error(
        "Scale settings are already active; review changes in Device Config",
      );
    }
    const { values } = captureSettings(stored.capture);
    if (
      scale.reported_feature_mask != null &&
      scale.reported_feature_mask !== values[3]
    ) {
      throw new Error(
        "Captured feature mask differs from authenticated scale request",
      );
    }
    if (timeZone) {
      if (timeZone.length > 100 || /^[./]/.test(timeZone))
        throw new Error("Invalid IANA time zone");
      zoneTriplet(timeZone);
    }
    statements.push(
      db
        .prepare(
          "UPDATE scales SET goff=?,dst=?,ngoff=?,feature_mask=?,debug_mask=?,beta_ws=?,temp_code=?,weight_code=?,screen_response=?,summary_response=?,weather_response=?,time_zone=?,settings_ready=1 WHERE id=? AND settings_ready=0 AND screen_response IS NULL AND summary_response IS NULL AND roster_enabled=0",
        )
        .bind(...values, timeZone, scale.id),
    );
  }
  await db.batch(statements);
}
function captureSettings(capture: Capture): { values: Value[] } {
  const ctp = capture.ctp,
    ind = capture.ind;
  if (!ctp || !ind) throw new Error("Capture has no time or device settings");
  const integer = (
    value: unknown,
    lo: number,
    hi: number,
    key: string,
  ): number => {
    if (!Number.isInteger(value) || Number(value) < lo || Number(value) > hi)
      throw new Error(`Invalid ${key}`);
    return Number(value);
  };
  const goff = integer(ctp.goff, -86400, 86400, "ctp.goff");
  const dst = integer(ctp.dst, -(2 ** 31), 2 ** 31 - 1, "ctp.dst");
  const ngoff = integer(ctp.ngoff, -86400, 86400, "ctp.ngoff");
  const fm = integer(ind.fm, 0, 2147483647, "ind.fm");
  const ws = integer(ind.ws, 0, 1, "ind.ws");
  if (ws !== 0)
    throw new Error("Captured routing selector points to a Withings beta host");
  const tmp = integer(ind.tmp, 0, 255, "ind.tmp");
  const weight = integer(ind.w, 0, 255, "ind.w");
  const screen = validatedFixture(
    JSON.stringify(capture.screen_response ?? null),
    "screen",
  );
  const summary = validatedFixture(
    JSON.stringify(capture.summary_response ?? null),
    "summary",
  );
  const weather = capture.weather_response
    ? validatedFixture(JSON.stringify(capture.weather_response), "weather")
    : null;
  if (!screen || !summary) throw new Error("Capture lacks display responses");
  return {
    values: [
      goff,
      dst,
      ngoff,
      fm,
      0,
      ws,
      tmp,
      weight,
      screen,
      summary,
      weather,
    ],
  };
}

async function updateMemberships(
  db: D1Database,
  userId: number,
  requested: number[],
): Promise<D1PreparedStatement[]> {
  if (requested.length !== new Set(requested).size)
    throw new Error("Duplicate scale selection");
  const available = await rows<{ id: number }>(db, "SELECT id FROM scales");
  if (requested.some((id) => !available.some((scale) => scale.id === id)))
    throw new Error("Unknown scale");
  for (const id of requested) {
    const count = await one<{ count: number }>(
      db,
      "SELECT COUNT(*) AS count FROM scale_users su JOIN users u ON u.id=su.user_id WHERE su.scale_id=? AND su.user_id<>? AND u.active=1",
      id,
      userId,
    );
    if ((count?.count ?? 0) >= 8)
      throw new Error("A scale can have at most eight users");
  }
  const current = await rows<{ scale_id: number }>(
    db,
    "SELECT scale_id FROM scale_users WHERE user_id=?",
    userId,
  );
  const currentIds = new Set(current.map((item) => item.scale_id));
  const statements: D1PreparedStatement[] = [];
  for (const id of currentIds)
    if (!requested.includes(id))
      statements.push(
        db
          .prepare("DELETE FROM scale_users WHERE scale_id=? AND user_id=?")
          .bind(id, userId),
      );
  for (const id of requested)
    if (!currentIds.has(id))
      statements.push(
        db
          .prepare(
            "INSERT INTO scale_users(scale_id,user_id,rank) VALUES(?,?,(SELECT COALESCE(MAX(rank),0)+1 FROM scale_users WHERE scale_id=?))",
          )
          .bind(id, userId, id),
      );
  return statements;
}
function parsedUser(form: FormData): {
  name: string;
  short: string;
  height: number;
  age: number;
  dob: string | null;
  sex: number;
  weight: number;
  scales: number[];
} {
  const name = formText(form, "name").trim();
  const short = formText(form, "short_name").trim().toUpperCase();
  const height = Math.round(formNumber(form, "height_cm"));
  const dob = formText(form, "birth_date") || null;
  const age = dob ? dateAge(dob) : formNumber(form, "age_years");
  const sex = formInteger(form, "sex");
  const weight = formNumber(form, "reference_weight_kg");
  const scales = form.getAll("scales").map((value) => Number(value));
  if (
    !name ||
    name.length > 100 ||
    !SHORT.test(short) ||
    height < 80 ||
    height > 250 ||
    age < 1 ||
    age > 120 ||
    ![0, 1].includes(sex) ||
    weight < 2 ||
    weight > 500 ||
    scales.some((id) => !Number.isInteger(id) || id < 1)
  )
    throw new Error("Invalid profile fields");
  return { name, short, height, age, dob, sex, weight, scales };
}

// Failed attempts only: ordinary household polling never consumes this budget.
async function authLimit(
  db: D1Database,
  request: Request,
  purpose: string,
  failed?: boolean,
): Promise<boolean> {
  const ip =
    request.headers.get("X-YOW-Peer-IP") ??
    request.headers.get("CF-Connecting-IP") ??
    "unknown";
  const key = await digest(`${purpose}:${ip}`),
    timestamp = now(),
    cutoff = timestamp - 600;
  if (failed === false) {
    await run(db, "DELETE FROM browser_auth_limits WHERE key=?", key);
    return false;
  }
  if (failed === true) {
    await db.batch([
      db
        .prepare("DELETE FROM browser_auth_limits WHERE window_start<?")
        .bind(cutoff),
      db
        .prepare(
          "INSERT INTO browser_auth_limits(key,window_start,attempts) VALUES(?,?,1) ON CONFLICT(key) DO UPDATE SET attempts=CASE WHEN window_start<? THEN 1 ELSE attempts+1 END,window_start=CASE WHEN window_start<? THEN excluded.window_start ELSE window_start END",
        )
        .bind(key, timestamp, cutoff, cutoff),
    ]);
  }
  const row = await one(
    db,
    "SELECT attempts FROM browser_auth_limits WHERE key=? AND window_start>=?",
    key,
    cutoff,
  );
  return (row?.attempts ?? 0) >= 20;
}
async function readingsAuthorized(
  db: D1Database,
  request: Request,
): Promise<boolean> {
  if (await authLimit(db, request, "sync")) return false;
  const separate =
    (await setting(db, "sync_password_mode")) === "separate" ||
    ((await setting(db, "sync_password_mode")) === null &&
      !!(await setting(db, "api_password")));
  const encoded = await setting(
    db,
    separate ? "api_password" : "admin_password",
  );
  const authorization = request.headers.get("Authorization") ?? "";
  if (/^Basic /i.test(authorization)) {
    try {
      const decoded = atob(authorization.slice(6));
      const colon = decoded.indexOf(":");
      const valid =
        colon > 0 &&
        decoded.slice(0, colon) === "reader" &&
        (await passwordMatches(decoded.slice(colon + 1), encoded));
      await authLimit(db, request, "sync", !valid);
      return valid;
    } catch {
      /* Invalid base64 is unauthenticated. */
    }
  }
  await authLimit(db, request, "sync", true);
  return false;
}
function readingsUnauthorized(): Response {
  return Response.json(
    { error: "readings API password required" },
    {
      status: 401,
      headers: {
        "WWW-Authenticate": 'Basic realm="WBS06 readings"',
        "Cache-Control": "no-store",
      },
    },
  );
}
async function resolveApiUser(
  db: D1Database,
  userRef: string,
): Promise<{ id: number; name: string } | Response> {
  if (/^\d+$/.test(userRef)) {
    const id = Number(userRef);
    if (!Number.isSafeInteger(id) || id < 1 || id > 2147483647)
      return json({ error: "Unknown user" }, 404);
    return (
      (await one<{ id: number; name: string }>(
        db,
        "SELECT id,name FROM users WHERE id=?",
        id,
      )) ?? json({ error: "Unknown user" }, 404)
    );
  }
  const matches = await rows<{ id: number; name: string }>(
    db,
    "SELECT id,name FROM users WHERE UPPER(short_name)=? AND active=1 ORDER BY id LIMIT 2",
    userRef.toUpperCase(),
  );
  if (matches.length > 1)
    return json(
      { error: "ambiguous short name; use the numeric user ID" },
      409,
    );
  return matches[0] ?? json({ error: "Unknown user" }, 404);
}
async function readingsApi(
  db: D1Database,
  request: Request,
  url: URL,
  userRef: string,
  includeMetrics = false,
): Promise<Response> {
  if (!(await readingsAuthorized(db, request))) return readingsUnauthorized();
  const user = await resolveApiUser(db, userRef);
  if (user instanceof Response) return user;
  const userId = user.id;
  const limit = Number(url.searchParams.get("limit") ?? "100");
  const before = Number(
    url.searchParams.get("before") ?? String(Number.MAX_SAFE_INTEGER),
  );
  if (
    !Number.isInteger(limit) ||
    limit < 1 ||
    limit > 1000 ||
    !Number.isSafeInteger(before) ||
    before < 0
  )
    return json({ error: "invalid pagination" }, 400);
  const since = url.searchParams.get("since") ?? "1970-01-01",
    date = new Date(`${since}T00:00:00Z`);
  if (
    !/^\d{4}-\d{2}-\d{2}$/.test(since) ||
    !Number.isFinite(date.valueOf()) ||
    date.toISOString().slice(0, 10) !== since
  )
    return json({ error: "invalid since date" }, 400);
  const cursor = url.searchParams.get("cursor");
  const parts = cursor?.match(/^(\d+):(\d+)$/);
  if (
    cursor &&
    (!parts || !parts.slice(1).every((v) => Number.isSafeInteger(Number(v))))
  )
    return json({ error: "invalid cursor" }, 400);
  const cursorTime = parts ? Number(parts[1]) : Number.MAX_SAFE_INTEGER;
  const cursorId = parts ? Number(parts[2]) : Number.MAX_SAFE_INTEGER;
  const ordering =
    "(CASE WHEN r.time_quality='trusted' THEN r.meastime ELSE r.first_received_at END)";
  const matches = await rows(
    db,
    `SELECT r.*,s.label AS scale_label,h.synced_at AS health_sync_acknowledged_at
    FROM readings r JOIN scales s ON s.id=r.scale_id
    LEFT JOIN health_sync_receipts h ON h.reading_id=r.id AND h.user_id=r.user_id
    WHERE r.user_id=? ${includeMetrics ? "" : "AND r.weight_value IS NOT NULL"} AND ${ordering}<?
    AND ${ordering}>=? AND (${ordering}<? OR (${ordering}=? AND r.id<?))
    ORDER BY ${readingOrder} LIMIT ?`,
    userId,
    before,
    Math.floor(date.valueOf() / 1000),
    cursorTime,
    cursorTime,
    cursorId,
    limit + (includeMetrics ? 1 : 0),
  );
  const page = matches.slice(0, limit);
  const last = page.at(-1);
  return json({
    user,
    ...(includeMetrics
      ? {
          available_metrics: await observedMetrics(db, userId),
          next_cursor:
            matches.length > limit && last
              ? `${last.time_quality === "trusted" ? last.meastime : last.first_received_at}:${last.id}`
              : null,
        }
      : {}),
    readings: page.map((r) => ({
      id: r.id,
      scale: r.scale_label,
      meastime: r.meastime,
      timestamp:
        r.time_quality === "trusted"
          ? new Date(r.meastime * 1000).toISOString()
          : null,
      time_quality: r.time_quality,
      received_at: new Date(r.first_received_at * 1000).toISOString(),
      ordering_time:
        r.time_quality === "trusted" ? r.meastime : r.first_received_at,
      weight_kg:
        r.weight_value === null
          ? null
          : exactWeight(Number(r.weight_value), Number(r.weight_unit)),
      ...(includeMetrics
        ? {
            metrics: namedMetrics(r),
            measures: storedMeasures(r),
            group: r.group_json
              ? JSON.parse(r.group_json)
              : { meastime: r.meastime, measures: storedMeasures(r) },
          }
        : {}),
      value: r.weight_value,
      unit: r.weight_unit,
      attribution: r.attribution,
      candidate_ids: parseJson(r.candidate_ids),
      health_sync_acknowledged_at: r.health_sync_acknowledged_at
        ? new Date(Number(r.health_sync_acknowledged_at) * 1000).toISOString()
        : null,
    })),
  });
}

async function healthSyncApi(
  db: D1Database,
  request: Request,
  url: URL,
  userRef: string,
  operation: string,
): Promise<Response> {
  if (!(await readingsAuthorized(db, request))) return readingsUnauthorized();
  const user = await resolveApiUser(db, userRef);
  if (user instanceof Response) return user;
  const userId = user.id;
  if (operation === "ack") {
    const readingId = Number(url.searchParams.get("reading_id"));
    if (!Number.isSafeInteger(readingId) || readingId < 1)
      return json({ error: "invalid reading_id" }, 400);
    const reading = await one<{ id: number }>(
      db,
      "SELECT id FROM readings WHERE id=? AND user_id=? AND weight_value IS NOT NULL",
      readingId,
      userId,
    );
    if (!reading) return json({ error: "Unknown reading" }, 404);
    await run(
      db,
      "INSERT OR IGNORE INTO health_sync_receipts(user_id,reading_id,synced_at) VALUES(?,?,?)",
      userId,
      readingId,
      now(),
    );
    return json({ ok: true, reading_id: readingId });
  }
  const since = url.searchParams.get("since") ?? "1970-01-01";
  const sinceDate = new Date(`${since}T00:00:00Z`);
  if (
    !/^\d{4}-\d{2}-\d{2}$/.test(since) ||
    !Number.isFinite(sinceDate.valueOf()) ||
    sinceDate.toISOString().slice(0, 10) !== since
  )
    return json({ error: "invalid since date" }, 400);
  const row = await one<Row>(
    db,
    `SELECT r.*,s.label AS scale_label FROM readings r JOIN scales s ON s.id=r.scale_id
    LEFT JOIN health_sync_receipts h ON h.user_id=? AND h.reading_id=r.id
    WHERE r.user_id=? AND r.weight_value IS NOT NULL AND h.reading_id IS NULL AND r.first_received_at>=? ORDER BY r.id ASC LIMIT 1`,
    userId,
    userId,
    Math.floor(sinceDate.valueOf() / 1000),
  );
  return json({
    user,
    reading: row
      ? {
          id: row.id,
          scale: row.scale_label,
          weight_kg: exactWeight(
            Number(row.weight_value),
            Number(row.weight_unit),
          ),
          date: new Date(
            (row.time_quality === "trusted"
              ? row.meastime
              : row.first_received_at) * 1000,
          ).toISOString(),
          time_quality: row.time_quality,
        }
      : null,
  });
}

/** Apply the imported profile automatically, never copy Body display fields to WS-30. */
async function fetchAndApplyProfile(
  db: D1Database,
  scale: Row,
  fetcher: (scale: Row) => Promise<string>,
  zone: string | null,
) {
  if (scale.model === "WBS13")
    throw new Error(
      "WBS13 uses local users; choose them in Scales → Edit Settings",
    );
  const raw = await fetcher(scale);
  await stageCapture(db, scale.id, raw);
  const capture = parseCapture(raw),
    statements: D1PreparedStatement[] = [];
  // Preserve an established local roster and locally edited users on refresh.
  if (!scale.roster_snapshot)
    statements.push(
      db
        .prepare("UPDATE scales SET roster_snapshot=? WHERE id=?")
        .bind(JSON.stringify(capture.sp!.users), scale.id),
    );
  if (zone) {
    zoneTriplet(zone);
    statements.push(
      db
        .prepare("UPDATE scales SET time_zone=? WHERE id=?")
        .bind(zone, scale.id),
    );
  }
  if (scale.model === "WBS06" && !scale.settings_ready) {
    const { values } = captureSettings(capture);
    if (
      scale.reported_feature_mask != null &&
      scale.reported_feature_mask !== values[3]
    )
      throw new Error(
        "Captured settings do not match this scale's reported feature mask",
      );
    statements.push(
      db
        .prepare(
          "UPDATE scales SET goff=?,dst=?,ngoff=?,feature_mask=?,debug_mask=?,beta_ws=?,temp_code=?,weight_code=?,screen_response=?,summary_response=?,weather_response=?,settings_ready=1 WHERE id=? AND settings_ready=0",
        )
        .bind(...values, scale.id),
    );
  }
  // Existing IDs mean the same person. Associate them without replacing edits.
  for (const [rank, user] of capture.sp!.users.entries())
    statements.push(
      db
        .prepare(
          "INSERT OR IGNORE INTO scale_users(scale_id,user_id,rank) SELECT ?,id,? FROM users WHERE id=?",
        )
        .bind(scale.id, rank + 1, user.id),
    );
  if (statements.length) await db.batch(statements);
  return previewProfile(db, scale.id);
}
async function previewProfile(db: D1Database, id: number) {
  const scale = await one(db, "SELECT * FROM scales WHERE id=?", id),
    stored = await reviewedCapture(db, id);
  const known = new Set(
    (await rows(db, "SELECT id FROM users")).map((u) => u.id),
  );
  return {
    scaleId: id,
    model: scale?.model,
    settingsReady: scale?.model === "WBS03" || scale?.settings_ready === 1,
    digest: stored?.digest,
    users:
      stored?.capture
        .sp!.users.filter((u) => !known.has(u.id))
        .map((u) => ({
          id: u.id,
          name: u.fn || u.sn,
          shortName: u.sn,
          sex: u.sx,
          heightCm: Math.round(u.ht * 100),
          age: u.agt,
          weightKg: u.wt,
        })) ?? [],
  };
}
async function enrollDevice(
  db: D1Database,
  record: Row,
  label: string,
  zone: string | null,
): Promise<Row> {
  label =
    label.trim() ||
    `${record.model === "WBS03" ? "WS-30" : record.model === "WBS13" ? "Body Smart" : record.model === "WBS04" ? "Body Cardio" : "Body"} ${record.mac.slice(-4)}`;
  if (label.length > 80) throw new Error("Scale label is too long");
  if (zone) zoneTriplet(zone);
  const existing = await one(
    db,
    "SELECT * FROM scales WHERE mac=?",
    record.mac,
  );
  if (existing && !equal(existing.secret, record.session_secret))
    throw new Error("Enrolled scale has a different secret");
  if (
    existing?.ble_captured_at &&
    record.captured_at < existing.ble_captured_at
  )
    throw new Error("Device export is older than the saved one");
  const meta: Value[] = [
    record.name,
    record.probe_identifier ?? "",
    record.hardware_version,
    record.bootloader_version,
    record.firmware_version,
    record.rescue_version,
    record.wifi_ssid ?? null,
    record.owner_host ?? null,
    record.owner_transport ?? null,
    record.captured_at,
  ];
  if (existing) {
    await run(
      db,
      "UPDATE scales SET model=?,ble_name=?,ble_probe_identifier=?,ble_hardware_version=?,ble_bootloader_version=?,ble_firmware_version=?,ble_rescue_version=?,ble_wifi_ssid=?,ble_owner_host=?,ble_owner_transport=?,ble_captured_at=?,time_zone=COALESCE(time_zone,?) WHERE id=?",
      record.model,
      ...meta,
      zone,
      existing.id,
    );
  } else
    await run(
      db,
      "INSERT INTO scales(label,model,mac,secret,ble_name,ble_probe_identifier,ble_hardware_version,ble_bootloader_version,ble_firmware_version,ble_rescue_version,ble_wifi_ssid,ble_owner_host,ble_owner_transport,ble_captured_at,time_zone) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
      label,
      record.model,
      record.mac,
      record.session_secret,
      ...meta,
      zone,
    );
  const saved = (await one(
    db,
    "SELECT * FROM scales WHERE mac=?",
    record.mac,
  ))!;
  await firmwareObservation(
    db,
    saved.id,
    record.firmware_version,
    record.captured_at,
    "bluetooth",
  ).run();
  return saved;
}
async function queueRosterEdits(db: D1Database, userId: number) {
  for (const scale of await rows(
    db,
    "SELECT * FROM scales WHERE model='WBS06' AND settings_ready=1 AND roster_snapshot IS NOT NULL",
  )) {
    const baseline = JSON.parse(scale.roster_snapshot);
    if (!baseline.some((u: Row) => u.id === userId)) continue;
    try {
      await roster({ DB: db }, scale as any);
      await run(db, "UPDATE scales SET roster_enabled=1 WHERE id=?", scale.id);
    } catch {
      await run(db, "UPDATE scales SET roster_enabled=0 WHERE id=?", scale.id);
    }
  }
}
async function integratedApi(request: Request, env: AppEnv): Promise<Response> {
  const url = new URL(request.url),
    path = url.pathname,
    db = env.DB;
  if (path === "/api/devices" && request.method === "GET")
    return json({
      devices: await rows(
        db,
        "SELECT id,model,mac,label,last_session_at,settings_ready,time_zone,firmware_version,firmware_confirmed_at,firmware_source FROM scales ORDER BY id",
      ),
    });
  if (path === "/api/config/time" && request.method === "GET") {
    const zone = url.searchParams.get("zone") || "UTC";
    return json({ utcSeconds: now(), ...zoneTriplet(zone) });
  }
  const status = /^\/api\/scales\/(\d+)\/connection-status$/.exec(path);
  if (status && request.method === "GET") {
    const scale = await one(
      db,
      "SELECT id,last_session_at FROM scales WHERE id=?",
      Number(status[1]),
    );
    if (!scale) return json({ error: "Unknown scale" }, 404);
    const reading = await one(
      db,
      "SELECT MAX(first_received_at) AS lastReadingAt FROM readings WHERE scale_id=?",
      scale.id,
    );
    return json({ ...scale, ...reading });
  }
  if (request.method !== "POST") return json({ error: "Not found" }, 404);
  const body = (await request.json()) as Row;
  if (path === "/api/firmware/offer") {
    if (!env.lookupFirmwareOffer)
      return json({ error: "Firmware lookup is unavailable" }, 503);
    return json(await env.lookupFirmwareOffer(body));
  }
  const observation = /^\/api\/scales\/(\d+)\/firmware-observation$/.exec(path);
  if (observation) {
    const scale = await one(
      db,
      "SELECT id,mac,model FROM scales WHERE id=?",
      Number(observation[1]),
    );
    if (!scale) return json({ error: "Unknown scale" }, 404);
    if (
      typeof body.mac !== "string" ||
      canonicalMac(body.mac) !== scale.mac ||
      body.model !== scale.model
    )
      throw new Error("Probe identity does not match the registered scale");
    const version = firmwareVersion(body.firmwareVersion);
    const observedAt =
      typeof body.observedAt === "string"
        ? Math.floor(Date.parse(body.observedAt) / 1000)
        : NaN;
    if (version === null) throw new Error("Invalid firmware version");
    await firmwareObservation(
      db,
      scale.id,
      version,
      observedAt,
      "bluetooth",
    ).run();
    return json({ saved: true });
  }
  const timezone = /^\/api\/scales\/(\d+)\/time-zone$/.exec(path);
  if (timezone) {
    if (typeof body.timeZone !== "string" || !body.timeZone)
      throw new Error("Choose a time zone");
    zoneTriplet(body.timeZone);
    const id = Number(timezone[1]);
    if (!(await one(db, "SELECT id FROM scales WHERE id=?", id)))
      return json({ error: "Unknown scale" }, 404);
    await run(
      db,
      "UPDATE scales SET time_zone=? WHERE id=?",
      body.timeZone,
      id,
    );
    return json({ saved: true, timeZone: body.timeZone });
  }
  if (path === "/api/scales/enroll") {
    const record = parseDeviceRecord(JSON.stringify(body.device));
    const zone = typeof body.timeZone === "string" ? body.timeZone : null;
    const scale = await enrollDevice(
      db,
      record,
      String(body.label ?? ""),
      zone,
    );
    if (scale.model === "WBS13")
      return json({
        scaleId: scale.id,
        localRoster: true,
        message:
          "Device saved. Choose its users in Scales → Edit Settings before its first sync.",
      });
    try {
      if (!env.captureWithings) throw new Error("Withings import unavailable");
      return json(
        await fetchAndApplyProfile(db, scale, env.captureWithings, zone),
      );
    } catch {
      return json({
        ...(await previewProfile(db, scale.id)),
        migrationIncomplete: true,
        message:
          "Device saved. Withings profile import is incomplete. Use Finish Device Import to retry.",
      });
    }
  }
  const migration = /^\/api\/scales\/(\d+)\/migration$/.exec(path);
  if (migration) {
    const scale = await one(
      db,
      "SELECT * FROM scales WHERE id=?",
      Number(migration[1]),
    );
    if (!scale || !env.captureWithings)
      throw new Error("Scale or Withings import unavailable");
    return json(
      await fetchAndApplyProfile(
        db,
        scale,
        env.captureWithings,
        scale.time_zone,
      ),
    );
  }
  const confirm = /^\/api\/scales\/(\d+)\/import-users$/.exec(path);
  if (confirm) {
    const scale = await one(
      db,
      "SELECT * FROM scales WHERE id=?",
      Number(confirm[1]),
    );
    const stored = scale ? await reviewedCapture(db, scale.id) : null;
    if (!scale || !stored || body.digest !== stored.digest)
      throw new Error("Imported profile changed; fetch it again");
    if (
      !Array.isArray(body.userIds) ||
      body.userIds.some(
        (id: unknown) =>
          !Number.isInteger(id) ||
          !stored.capture.sp!.users.some((u) => u.id === id),
      )
    )
      throw new Error("Choose users from this imported profile");
    await importCaptureUsers(
      db,
      scale,
      stored,
      false,
      null,
      new Set(body.userIds),
    );
    return json({ imported: true });
  }
  return json({ error: "Not found" }, 404);
}

export async function handleApp(
  request: Request,
  env: AppEnv,
): Promise<Response> {
  const db = env.DB;
  const url = new URL(request.url);
  const path = url.pathname;
  const method = request.method;
  if (
    [
      "/app.css",
      "/app.js",
      "/firmware.js",
      "/favicon.png",
      "/YourOwnWeigh-Sync.shortcut",
    ].includes(path) &&
    method === "GET"
  ) {
    return env.ASSETS
      ? env.ASSETS.fetch(request)
      : new Response("Not Found", { status: 404 });
  }
  if (SCALE_PATHS.has(path)) {
    if (method !== "POST") return new Response("Not Found", { status: 404 });
    if (
      url.protocol !== "https:" &&
      !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname) &&
      !env.ALLOW_HTTP_SCALE
    )
      return new Response("HTTPS required", { status: 403 });
    return (
      (await handleScaleRequest(request, env)) ??
      new Response("Not Found", { status: 404 })
    );
  }
  if (
    url.protocol !== "https:" &&
    !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)
  ) {
    const target = new URL(request.url);
    target.protocol = "https:";
    target.port = "";
    return new Response(null, {
      status: 308,
      headers: { Location: target.href },
    });
  }
  if (path === "/health" && method === "GET") {
    try {
      await db.prepare("SELECT 1 AS ready FROM admin_sessions LIMIT 1").first();
      return json({ ok: true, database: "ready" });
    } catch {
      return json({ ok: false, database: "migration required" }, 503);
    }
  }
  const api = /^\/api\/users\/(\d+|[A-Za-z]{3})\/(weights|readings)$/.exec(
    path,
  );
  if (api && method === "GET")
    return readingsApi(db, request, url, api[1], api[2] === "readings");
  const healthSync =
    /^\/api\/users\/(\d+|[A-Za-z]{3})\/health-sync\/(next|ack)$/.exec(path);
  if (
    healthSync &&
    ((healthSync[2] === "next" && method === "GET") ||
      (healthSync[2] === "ack" && method === "POST"))
  )
    return healthSyncApi(db, request, url, healthSync[1], healthSync[2]);
  if (
    request.headers.has("Content-Length") &&
    Number(request.headers.get("Content-Length")) >
      (path === "/api/backup/import" ? 10 * 1024 * 1024 : 256000)
  ) {
    return new Response("Request too large", { status: 413 });
  }

  if (["/api/bridge/exchange", "/api/bridge/socket"].includes(path)) {
    return env.bridgeRequest
      ? env.bridgeRequest(request, null)
      : json({ error: "Bridge is unavailable" }, 503);
  }
  const adminConfigured = !!(await setting(db, "admin_password"));
  if (!cookieValue(request) && path !== "/setup" && path !== "/login") {
    return redirect(adminConfigured ? "/login" : "/setup");
  }
  if (
    !adminConfigured &&
    path === "/setup" &&
    !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname) &&
    (!env.YOW_BOOTSTRAP_TOKEN || env.YOW_BOOTSTRAP_TOKEN.length < 24)
  ) {
    return new Response(
      "Set YOW_BOOTSTRAP_TOKEN before public first-run setup",
      { status: 503 },
    );
  }
  const { row: browser, cookie } = await browserSession(db, request);
  const csrf = browser.csrf;
  const loggedIn = await authenticated(db, browser);
  if (path.startsWith("/api/bridge/")) {
    if (!loggedIn) return json({ error: "Sign in first" }, 401);
    if (
      request.headers.get("Origin") !== url.origin &&
      (method === "POST" || path.endsWith("/ui/socket"))
    )
      return json({ error: "Invalid request origin" }, 403);
    if (
      method === "POST" &&
      !equal(request.headers.get("X-CSRF-Token") ?? "", csrf)
    )
      return json({ error: "Invalid CSRF token" }, 403);
    return env.bridgeRequest
      ? env.bridgeRequest(request, browser.token_hash)
      : json({ error: "Bridge is unavailable" }, 503);
  }
  if (
    path.startsWith("/api/scales/") ||
    path === "/api/firmware/offer" ||
    path === "/api/devices" ||
    path === "/api/config/time"
  ) {
    if (!loggedIn) return json({ error: "Sign in first" }, 401);
    if (
      method === "POST" &&
      (!equal(request.headers.get("X-CSRF-Token") ?? "", csrf) ||
        request.headers.get("Origin") !== url.origin)
    )
      return json({ error: "Invalid request origin or CSRF token" }, 403);
    try {
      return await integratedApi(request, env);
    } catch (error) {
      return json({ error: safeError(error) }, 400);
    }
  }
  const notice = (url.searchParams.get("notice") ?? "").slice(0, 250);
  const page = (title: string, body: string, active = "") =>
    html(layout(title, body, csrf, loggedIn, notice, active), 200, cookie);
  const go = (location: string, message = "") =>
    redirect(location, message, cookie);
  if (path.startsWith("/api/backup/")) {
    if (!loggedIn) return json({ error: "Sign in first" }, 401);
    try {
      if (path === "/api/backup/export" && method === "GET")
        return new Response(JSON.stringify(await exportBackup(db), null, 2), {
          headers: {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "Content-Disposition": `attachment; filename="yow-${new Date().toISOString().slice(0, 10)}.json"`,
          },
        });
      if (method !== "POST") return json({ error: "Not found" }, 404);
      const form = await request.formData();
      if (!equal(formText(form, "_csrf"), csrf))
        return json({ error: "Invalid CSRF token" }, 403);
      if (path === "/api/backup/import") {
        const file = form.get("backup");
        if (!(file instanceof File) || file.size > 10 * 1024 * 1024)
          throw new Error("Choose a backup file of at most 10 MiB");
        const staged = await stageBackup(
          db,
          await file.text(),
          browser.token_hash,
        );
        return page(
          "Review Backup Import",
          `<section><h1>Review Backup Import</h1><dl>${Object.entries(
            staged.counts,
          )
            .map(
              ([name, count]) =>
                `<dt>${escapeHtml(name.replaceAll("_", " "))}</dt><dd>${count}</dd>`,
            )
            .join(
              "",
            )}</dl><form action="/api/backup/commit" method="post"><input type="hidden" name="_csrf" value="${csrf}"><input type="hidden" name="import_id" value="${staged.id}"><input type="hidden" name="digest" value="${staged.digest}"><label><input type="radio" name="mode" value="merge" checked> Add Missing Data (Keep Existing Edits)</label><label><input type="radio" name="mode" value="replace"> Replace Household Data</label><p>Replacement removes current users, readings and devices. <a href="/api/backup/export">Export Current Data First</a>.</p>${staged.hasAccess ? '<label><input type="checkbox" name="restore_access" value="1"> Restore Access Settings (Use The Backup’s Passwords And Sign Out)</label>' : ""}<label><input type="checkbox" name="confirmed" value="1" required> I Have Reviewed This Import</label><div class="dialog-actions"><button>Import Backup</button><a href="/settings">Cancel</a></div></form></section>`,
          "/settings",
        );
      }
      if (path === "/api/backup/commit") {
        if (formText(form, "confirmed") !== "1")
          throw new Error("Confirm the reviewed import first");
        const restore = formText(form, "restore_access") === "1";
        await commitBackup(
          db,
          formText(form, "import_id"),
          formText(form, "digest"),
          browser.token_hash,
          formText(form, "mode") as "merge" | "replace",
          restore,
        );
        if (restore && env.bridgeRequest)
          await env.bridgeRequest(
            new Request(new URL("/api/bridge/revoke", url), { method: "POST" }),
            browser.token_hash,
          );
        return go(
          restore ? "/login" : "/settings",
          restore
            ? "Backup restored. Sign in with the backup’s admin password."
            : "Backup imported. Current passwords retained.",
        );
      }
    } catch (error) {
      return page(
        "Import Not Completed",
        `<section><h1>Import Not Completed</h1><p>${escapeHtml(safeError(error))}</p><a href="/settings">Back To Settings</a></section>`,
        "/settings",
      );
    }
    return json({ error: "Not found" }, 404);
  }
  if (method === "POST") {
    const submitted = await request.formData();
    if (!equal(formText(submitted, "_csrf"), csrf))
      return new Response("Invalid CSRF token", { status: 403 });
    return browserPost(
      request,
      db,
      path,
      submitted,
      browser,
      loggedIn,
      cookie,
      env.YOW_BOOTSTRAP_TOKEN,
      env.captureWithings,
    );
  }
  if (method !== "GET")
    return new Response("Method Not Allowed", { status: 405 });
  if (!adminConfigured) {
    if (path !== "/setup") return go("/setup");
    return page(
      "First-Run Setup",
      setupPage(csrf, !!env.YOW_BOOTSTRAP_TOKEN, browser.is_admin === 2),
    );
  }
  if (path === "/setup") return go("/login");
  if (path === "/login")
    return loggedIn ? go("/") : page("Sign In", loginPage(csrf));
  if (!loggedIn) return go("/login");
  if (path === "/") {
    const users = await rows(
      db,
      "SELECT * FROM users WHERE active=1 ORDER BY id",
    );
    const cards = [];
    for (const user of users) {
      const metrics = await observedMetrics(db, user.id);
      const metric =
        metrics.find(
          (m) => m.type === Number(url.searchParams.get(`metric_${user.id}`)),
        )?.type ?? 1;
      cards.push({
        user,
        metrics,
        metric,
        readings: await rows(
          db,
          `SELECT r.*,s.label AS scale_label FROM readings r JOIN scales s ON s.id=r.scale_id
      WHERE r.user_id=? AND ${metric === 1 ? "r.weight_value IS NOT NULL" : "EXISTS (SELECT 1 FROM json_each(r.measures_json) m WHERE json_extract(m.value,'$.type')=?)"} ORDER BY ${readingOrder} LIMIT 5`,
          user.id,
          ...(metric === 1 ? [] : [metric]),
        ),
      });
    }
    return page(
      "Dashboard",
      dashboardPage(cards, (await setting(db, "display_weight_unit")) ?? "kg"),
      "/",
    );
  }
  if (path === "/readings") {
    const metrics = await observedMetrics(db);
    const metric =
      metrics.find((m) => m.type === Number(url.searchParams.get("metric")))
        ?.type ?? 1;
    const users = await rows(
      db,
      "SELECT id,name FROM users WHERE active=1 ORDER BY name,id",
    );
    const readings = await rows(
      db,
      `SELECT r.*,s.label AS scale_label,u.name AS user_name,
      h.synced_at AS health_sync_acknowledged_at FROM readings r JOIN scales s ON s.id=r.scale_id
      LEFT JOIN users u ON u.id=r.user_id LEFT JOIN health_sync_receipts h ON h.reading_id=r.id AND h.user_id=r.user_id
      WHERE ${metric === 1 ? "r.weight_value IS NOT NULL" : "EXISTS (SELECT 1 FROM json_each(r.measures_json) m WHERE json_extract(m.value,'$.type')=?)"}
      ORDER BY ${readingOrder} LIMIT 10`,
      ...(metric === 1 ? [] : [metric]),
    );
    return page(
      "Readings",
      readingsPage(
        readings,
        users,
        (await setting(db, "display_weight_unit")) ?? "kg",
        csrf,
        metrics,
        metric,
      ),
      "/readings",
    );
  }
  const userReadings = /^\/users\/(\d+)\/readings$/.exec(path);
  if (userReadings) {
    const id = Number(userReadings[1]);
    const user = await one(db, "SELECT * FROM users WHERE id=?", id);
    if (!user) return new Response("Not Found", { status: 404 });
    const metrics = await observedMetrics(db, id);
    const metric =
      metrics.find((m) => m.type === Number(url.searchParams.get("metric")))
        ?.type ?? 1;
    const readings = await rows(
      db,
      `SELECT r.*,s.label AS scale_label,h.synced_at AS health_sync_acknowledged_at
      FROM readings r JOIN scales s ON s.id=r.scale_id
      LEFT JOIN health_sync_receipts h ON h.reading_id=r.id AND h.user_id=r.user_id
      WHERE r.user_id=? AND ${metric === 1 ? "r.weight_value IS NOT NULL" : "EXISTS (SELECT 1 FROM json_each(r.measures_json) m WHERE json_extract(m.value,'$.type')=?)"} ORDER BY ${readingOrder}`,
      id,
      ...(metric === 1 ? [] : [metric]),
    );
    return page(
      `${user.name} Readings`,
      userReadingsPage(
        user,
        readings,
        (await setting(db, "display_weight_unit")) ?? "kg",
        metrics,
        metric,
      ),
      "/readings",
    );
  }
  if (path === "/firmware") {
    return page("Firmware Bridge", firmwareWorkspace(csrf), "/firmware");
  }
  if (path === "/scales" || /^\/scales\/\d+$/.test(path)) {
    const scales = await rows(db, "SELECT * FROM scales ORDER BY label,id");
    const captures = new Map<number, Row>();
    for (const scale of scales) {
      const capture = await reviewedCapture(db, scale.id);
      if (capture)
        captures.set(scale.id, {
          ctp: capture.capture.ctp,
          ind: capture.capture.ind,
        });
    }
    const localUsers = await rows(
      db,
      "SELECT id,name FROM users WHERE active=1 ORDER BY name,id",
    );
    for (const scale of scales)
      scale.userIds = (
        await rows(
          db,
          "SELECT user_id FROM scale_users WHERE scale_id=?",
          scale.id,
        )
      ).map((r) => r.user_id);
    return page("Scales", scalesWorkspace(scales, csrf, localUsers), "/scales");
  }
  if (path === "/users" || /^\/users\/\d+$/.test(path)) {
    const users = await rows(
      db,
      "SELECT * FROM users ORDER BY active DESC,name,id",
    );
    const scales = await rows(db, "SELECT * FROM scales ORDER BY label,id");
    const memberships = new Map<number, Set<number>>();
    for (const user of users)
      memberships.set(
        user.id,
        new Set(
          (
            await rows<{ scale_id: number }>(
              db,
              "SELECT scale_id FROM scale_users WHERE user_id=?",
              user.id,
            )
          ).map((item) => item.scale_id),
        ),
      );
    let preview:
      | {
          scale: Row;
          users: Row[];
          digest: string;
          settingsStatus: "available" | "configured" | "unavailable";
          settings?: {
            goff: number;
            dst: number;
            ngoff: number;
            featureMask: number;
            temperatureCode: number;
            weightCode: number;
            hasWeather: boolean;
          };
        }
      | undefined;
    const requested = Number(url.searchParams.get("preview_scale"));
    if (Number.isInteger(requested) && requested > 0) {
      const scale = scales.find((item) => item.id === requested);
      if (scale) {
        const reviewed = await reviewedCapture(db, scale.id);
        if (reviewed) {
          preview = {
            scale,
            users: reviewed.capture.sp!.users.filter(
              (item) => !users.some((user) => user.id === item.id),
            ),
            digest: reviewed.digest,
            settingsStatus: "unavailable",
          };
          if (
            scale.settings_ready ||
            scale.screen_response ||
            scale.summary_response ||
            scale.roster_enabled
          ) {
            preview.settingsStatus = "configured";
          } else {
            try {
              const { values } = captureSettings(reviewed.capture);
              if (
                scale.reported_feature_mask != null &&
                scale.reported_feature_mask !== values[3]
              ) {
                throw new Error("Captured feature mask differs from scale");
              }
              preview.settingsStatus = "available";
              preview.settings = {
                goff: Number(values[0]),
                dst: Number(values[1]),
                ngoff: Number(values[2]),
                featureMask: Number(values[3]),
                temperatureCode: Number(values[6]),
                weightCode: Number(values[7]),
                hasWeather: values[10] !== null,
              };
            } catch {
              /* Users can still be imported from an incomplete settings capture. */
            }
          }
        }
      }
    }
    const importScaleId = Number(url.searchParams.get("import_scale"));
    return page(
      "Users",
      usersPage(
        users,
        scales,
        memberships,
        csrf,
        preview,
        env.captureWithings ? "verified-tls" : undefined,
        scales.some((scale) => scale.id === importScaleId)
          ? importScaleId
          : undefined,
      ),
      "/users",
    );
  }
  if (path === "/sync")
    return page(
      "Sync",
      syncPage(
        url.origin,
        await rows(db, "SELECT * FROM users WHERE active=1 ORDER BY name"),
      ),
      "/sync",
    );
  if (path === "/preferences" || path === "/settings") {
    const mode = await setting(db, "sync_password_mode");
    return page(
      "Settings",
      settingsWorkspace(
        csrf,
        (await setting(db, "display_weight_unit")) ?? "kg",
        mode === "separate" ||
          (mode === null && !!(await setting(db, "api_password"))),
      ),
      "/settings",
    );
  }
  return new Response("Not Found", { status: 404 });
}

async function browserPost(
  request: Request,
  db: D1Database,
  path: string,
  form: FormData,
  session: BrowserSession,
  loggedIn: boolean,
  cookie?: string,
  bootstrapToken?: string,
  captureWithings?: (scale: Row) => Promise<string>,
): Promise<Response> {
  const go = (location: string, message = "", replacement = cookie) =>
    redirect(location, message, replacement);
  const secure = new URL(request.url).protocol === "https:";
  if (path === "/setup") {
    if (await setting(db, "admin_password")) return go("/login");
    if (bootstrapToken && session.is_admin !== 2) {
      if (await authLimit(db, request, "bootstrap"))
        return go("/setup", "Too many attempts; try again in ten minutes");
      if (!equal(formText(form, "bootstrap_token"), bootstrapToken)) {
        await authLimit(db, request, "bootstrap", true);
        return go("/setup", "Invalid bootstrap token");
      }
      await authLimit(db, request, "bootstrap", false);
      if (formText(form, "step") === "bootstrap") {
        const token = randomHex(32);
        await db.batch([
          db
            .prepare("DELETE FROM admin_sessions WHERE token_hash=?")
            .bind(session.token_hash),
          db
            .prepare(
              "INSERT INTO admin_sessions(token_hash,csrf,is_admin,auth_version,expires_at) VALUES(?,?,2,0,?)",
            )
            .bind(await digest(token), randomHex(24), now() + 600),
        ]);
        return go(
          "/setup",
          "",
          `${SESSION_COOKIE}=${token}; HttpOnly; ${secure ? "Secure; " : ""}SameSite=Strict; Path=/; Max-Age=600`,
        );
      }
    }
    if (formText(form, "password") !== formText(form, "confirm"))
      return go("/setup", "Passwords do not match");
    try {
      const encoded = await passwordHash(formText(form, "password"));
      const separate = formText(form, "separate_sync") === "1";
      if (
        separate &&
        formText(form, "sync_password") !== formText(form, "sync_confirm")
      )
        throw new Error("Sync passwords do not match");
      const syncHash = separate
        ? await passwordHash(formText(form, "sync_password"))
        : null;
      const inserted = await db.batch([
        db
          .prepare(
            "INSERT OR IGNORE INTO settings(key,value) VALUES('admin_password',?)",
          )
          .bind(encoded),
        db.prepare(
          "INSERT OR IGNORE INTO settings(key,value) VALUES('auth_version','1')",
        ),
        db
          .prepare(
            "INSERT OR IGNORE INTO settings(key,value) SELECT 'sync_password_mode',? WHERE (SELECT value FROM settings WHERE key='admin_password')=?",
          )
          .bind(separate ? "separate" : "shared", encoded),
        ...(syncHash
          ? [
              db
                .prepare(
                  "INSERT OR IGNORE INTO settings(key,value) SELECT 'api_password',? WHERE (SELECT value FROM settings WHERE key='admin_password')=?",
                )
                .bind(syncHash, encoded),
            ]
          : []),
      ]);
      if (inserted[0].meta.changes !== 1) return go("/login");
      return go(
        "/",
        "Administration password set",
        await rotateSession(db, session, true, secure),
      );
    } catch (error) {
      return go("/setup", safeError(error));
    }
  }
  if (path === "/login") {
    const encoded = await setting(db, "admin_password");
    if (!encoded) return go("/setup");
    if (await authLimit(db, request, "login"))
      return go("/login", "Too many attempts; try again in ten minutes");
    if (!(await passwordMatches(formText(form, "password"), encoded))) {
      await authLimit(db, request, "login", true);
      return go("/login", "Invalid password");
    }
    await authLimit(db, request, "login", false);
    return go("/", "Signed in", await rotateSession(db, session, true, secure));
  }
  if (!loggedIn) return go("/login");
  if (path === "/logout")
    return go(
      "/login",
      "Signed out",
      await rotateSession(db, session, false, secure),
    );

  try {
    if (path === "/settings") {
      const purpose = formText(form, "purpose");
      if (purpose === "sync_password") {
        if (
          !(await passwordMatches(
            formText(form, "current_admin"),
            await setting(db, "admin_password"),
          ))
        )
          throw new Error("Current admin password is incorrect");
        const separate = formText(form, "separate") === "1";
        if (separate && formText(form, "new") !== formText(form, "confirm"))
          throw new Error("Passwords do not match");
        const encoded = separate
          ? await passwordHash(formText(form, "new"))
          : null;
        await db.batch([
          saveSetting(
            db,
            "sync_password_mode",
            separate ? "separate" : "shared",
          ),
          encoded
            ? saveSetting(db, "api_password", encoded)
            : db.prepare("DELETE FROM settings WHERE key='api_password'"),
        ]);
        return go(
          "/settings",
          separate
            ? "Separate Sync API password saved"
            : "Sync API now uses the admin password",
        );
      }
      if (!["admin_password", "api_password"].includes(purpose))
        return new Response("Bad Request", { status: 400 });
      const old = await setting(db, "admin_password");
      const current = formText(
        form,
        purpose === "admin_password" ? "current" : "current_admin",
      );
      if (!(await passwordMatches(current, old)))
        throw new Error("Current admin password is incorrect");
      if (formText(form, "new") !== formText(form, "confirm"))
        throw new Error("New passwords do not match");
      const encoded = await passwordHash(formText(form, "new"));
      if (purpose === "admin_password") {
        const nextVersion =
          Number((await setting(db, "auth_version")) ?? "0") + 1;
        await db.batch([
          saveSetting(db, "admin_password", encoded),
          saveSetting(db, "auth_version", String(nextVersion)),
          db
            .prepare(
              "UPDATE admin_sessions SET auth_version=? WHERE token_hash=?",
            )
            .bind(nextVersion, session.token_hash),
        ]);
        return go(
          "/settings",
          "Admin password changed; other sessions were signed out",
        );
      }
      await db.batch([
        saveSetting(db, "api_password", encoded),
        saveSetting(db, "sync_password_mode", "separate"),
      ]);
      return go("/settings", "Readings API password set");
    }
    if (path === "/preferences") {
      const unit = formText(form, "weight_unit");
      if (!["kg", "lb", "st"].includes(unit))
        throw new Error("Invalid display unit");
      await db.batch([saveSetting(db, "display_weight_unit", unit)]);
      return go("/settings", "Display weight unit saved");
    }
    if (path === "/scales") {
      const label = formText(form, "label").trim();
      const mac = canonicalMac(formText(form, "mac"));
      const secret = formText(form, "secret");
      if (!label || label.length > 80 || !secret || secret.length > 256)
        throw new Error("Supply a label and exact scale secret");
      const result = await run(
        db,
        "INSERT INTO scales(label,model,mac,secret) VALUES(?,?,?,?)",
        label,
        "WBS06",
        mac,
        secret,
      );
      return go(
        `/scales#scale-${result.meta.last_row_id}`,
        "Scale added. Import a reviewed capture to stage its settings and users.",
      );
    }
    if (path === "/scales/import-ble") {
      const file = form.get("record");
      if (!(file instanceof File))
        throw new Error("Choose a device enrollment JSON file");
      const record = parseDeviceRecord(await file.text());
      const scale = await enrollDevice(
        db,
        record,
        formText(form, "label"),
        formText(form, "time_zone") || null,
      );
      if (scale.model === "WBS13")
        return go(
          `/scales#scale-${scale.id}`,
          "Body Smart saved. Choose its users in Edit Settings before its first sync.",
        );
      try {
        if (!captureWithings) throw new Error("Withings import is unavailable");
        await fetchAndApplyProfile(db, scale, captureWithings, scale.time_zone);
        return go(
          `/users?preview_scale=${scale.id}`,
          "Scale imported with settings. Choose any new users to add.",
        );
      } catch {
        return go(
          `/scales#scale-${scale.id}`,
          "Scale saved. Withings import is incomplete; use Finish Device Import to retry.",
        );
      }
    }

    if (path === "/users/fetch-withings") {
      if (!captureWithings)
        throw new Error(
          "Direct Withings capture is unavailable in this deployment",
        );
      const id = formInteger(form, "scale_id");
      const scale = await one(db, "SELECT * FROM scales WHERE id=?", id);
      if (!scale) throw new Error("Choose a known scale");
      await fetchAndApplyProfile(db, scale, captureWithings, scale.time_zone);
      return go(
        `/users?preview_scale=${id}`,
        "Device settings imported. Choose any new users to add.",
      );
    }
    const scaleCapture = /^\/scales\/(\d+)\/capture$/.exec(path);
    if (scaleCapture) {
      const file = form.get("capture");
      if (!(file instanceof File))
        throw new Error("Choose a capture JSON file");
      const id = Number(scaleCapture[1]);
      await stageCapture(db, id, await file.text());
      return go(
        `/users?preview_scale=${id}`,
        "Capture staged. Review users before import.",
      );
    }
    if (path === "/users/import-withings") {
      const id = formInteger(form, "scale_id");
      const file = form.get("capture");
      if (!(file instanceof File))
        throw new Error("Choose a capture JSON file");
      await stageCapture(db, id, await file.text());
      return go(
        `/users?preview_scale=${id}`,
        "Capture staged. Review users before import.",
      );
    }
    const scaleSettings = /^\/scales\/(\d+)\/capture-settings$/.exec(path);
    if (scaleSettings) {
      const id = Number(scaleSettings[1]);
      const scale = await one(db, "SELECT * FROM scales WHERE id=?", id);
      if (!scale) return new Response("Not Found", { status: 404 });
      if (
        scale.settings_ready ||
        scale.screen_response ||
        scale.summary_response ||
        scale.roster_enabled
      )
        throw new Error("Scale already has active settings or fixtures");
      const stored = await reviewedCapture(db, id);
      if (!stored || stored.capture.mac !== scale.mac)
        throw new Error("No reviewed capture for this scale");
      const { values } = captureSettings(stored.capture);
      if (
        scale.reported_feature_mask != null &&
        scale.reported_feature_mask !== values[3]
      )
        throw new Error(
          "Captured feature mask differs from authenticated scale request",
        );
      await run(
        db,
        "UPDATE scales SET goff=?,dst=?,ngoff=?,feature_mask=?,debug_mask=?,beta_ws=?,temp_code=?,weight_code=?,screen_response=?,summary_response=?,weather_response=?,settings_ready=1 WHERE id=? AND settings_ready=0",
        ...values,
        id,
      );
      return go(`/scales#scale-${id}`, "Captured scale settings imported");
    }
    const scalePath = /^\/scales\/(\d+)$/.exec(path);
    if (scalePath) {
      const id = Number(scalePath[1]);
      const scale = await one(db, "SELECT * FROM scales WHERE id=?", id);
      if (!scale) return new Response("Not Found", { status: 404 });
      const purpose = formText(form, "purpose");
      if (purpose === "device_config") {
        const label = formText(form, "label").trim();
        const zone = formText(form, "time_zone").trim() || null;
        if (!label || label.length > 80) throw new Error("Invalid scale name");
        if (zone) zoneTriplet(zone);
        // Preserve imported readiness, roster state and response fixtures.
        // Advanced fields are editable only for the model that consumes them.
        if (scale.model === "WBS13") {
          const ids = [
            ...new Set(form.getAll("user_ids").map((v) => Number(v))),
          ];
          if (
            !ids.length ||
            ids.length > 8 ||
            ids.some((v) => !Number.isSafeInteger(v) || v < 1)
          )
            throw new Error("Choose one to eight users for this scale");
          const available = await rows(
            db,
            `SELECT id FROM users WHERE active=1 AND id IN (${ids.map(() => "?").join(",")})`,
            ...ids,
          );
          if (available.length !== ids.length)
            throw new Error("Choose active household users");
          await db.batch([
            db.prepare("DELETE FROM scale_users WHERE scale_id=?").bind(id),
            ...ids.map((user, rank) =>
              db
                .prepare(
                  "INSERT INTO scale_users(scale_id,user_id,rank) VALUES(?,?,?)",
                )
                .bind(id, user, rank),
            ),
            db
              .prepare(
                "UPDATE scales SET label=?,time_zone=?,settings_ready=1 WHERE id=?",
              )
              .bind(label, zone || "UTC", id),
          ]);
        } else if (scale.model === "WBS03") {
          await run(
            db,
            "UPDATE scales SET label=?,time_zone=? WHERE id=?",
            label,
            zone,
            id,
          );
        } else {
          const goff = formInteger(form, "goff"),
            dst = formInteger(form, "dst"),
            ngoff = formInteger(form, "ngoff");
          const fm = formInteger(form, "feature_mask"),
            beta = formInteger(form, "beta_ws");
          const temp = formInteger(form, "temp_code"),
            weight = formInteger(form, "weight_code");
          if (
            Math.abs(goff) > 86400 ||
            Math.abs(ngoff) > 86400 ||
            dst < 0 ||
            dst > 0xffffffff ||
            fm < 0 ||
            fm > 0x7fffffff ||
            ![0, 1].includes(beta) ||
            temp < 0 ||
            temp > 255 ||
            weight < 0 ||
            weight > 255
          )
            throw new Error("Invalid internal device settings");
          await run(
            db,
            "UPDATE scales SET label=?,time_zone=?,goff=?,dst=?,ngoff=?,feature_mask=?,beta_ws=?,temp_code=?,weight_code=? WHERE id=?",
            label,
            zone,
            goff,
            dst,
            ngoff,
            fm,
            beta,
            temp,
            weight,
            id,
          );
        }
        return go(
          `/scales#scale-${id}`,
          "Device saved. Time-zone changes apply on the next Wi-Fi sync.",
        );
      }
      if (purpose === "basic_config") {
        const label = formText(form, "label").trim(),
          zone = formText(form, "time_zone").trim() || null;
        if (!label || label.length > 80) throw new Error("Invalid scale name");
        if (zone) zoneTriplet(zone);
        await run(
          db,
          "UPDATE scales SET label=?,time_zone=? WHERE id=?",
          label,
          zone,
          id,
        );
        return go(
          `/scales#scale-${id}`,
          "Settings saved for the next Wi-Fi connection",
        );
      }
      if (purpose === "config") {
        const label = formText(form, "label").trim();
        const timeZone = formText(form, "time_zone").trim() || null;
        if (!label || label.length > 80) throw new Error("Invalid scale name");
        if (timeZone) {
          if (timeZone.length > 100 || /^[./]/.test(timeZone))
            throw new Error("Invalid IANA time zone");
          zoneTriplet(timeZone);
        }
        if (scale.model === "WBS03") {
          if (formText(form, "roster_enabled") === "1")
            throw new Error("WS-30 roster delivery is not implemented yet");
          await run(
            db,
            "UPDATE scales SET label=?,time_zone=? WHERE id=?",
            label,
            timeZone,
            id,
          );
          return go(
            `/scales#scale-${id}`,
            "WS-30 name and time zone saved; other on-scale settings are retained",
          );
        }
        const goff = formInteger(form, "goff"),
          dst = formInteger(form, "dst"),
          ngoff = formInteger(form, "ngoff");
        const fm = formInteger(form, "feature_mask"),
          ws = formInteger(form, "beta_ws");
        const tmp = formInteger(form, "temp_code"),
          weight = formInteger(form, "weight_code");
        if (
          Math.abs(goff) > 86400 ||
          Math.abs(ngoff) > 86400 ||
          dst < -(2 ** 31) ||
          dst >= 2 ** 31 ||
          fm < 0 ||
          fm > 2147483647 ||
          ![0, 1].includes(ws) ||
          tmp < 0 ||
          tmp > 255 ||
          weight < 0 ||
          weight > 255
        )
          throw new Error("Invalid scale settings");
        const roster = formText(form, "roster_enabled") === "1" ? 1 : 0;
        if (roster) safeRoster(scale, await activeMembers(db, id));
        await run(
          db,
          "UPDATE scales SET label=?,goff=?,dst=?,ngoff=?,time_zone=?,feature_mask=?,debug_mask=0,beta_ws=?,temp_code=?,weight_code=?,settings_ready=?,roster_enabled=? WHERE id=?",
          label,
          goff,
          dst,
          ngoff,
          timeZone,
          fm,
          ws,
          tmp,
          weight,
          formText(form, "settings_ready") === "1" ? 1 : 0,
          roster,
          id,
        );
        return go(`/scales#scale-${id}`, "Scale configuration saved");
      }
      if (purpose === "secret") {
        const secret = formText(form, "secret");
        if (!secret || secret.length > 256)
          throw new Error("Secret must contain 1 to 256 characters");
        await db.batch([
          db.prepare("UPDATE scales SET secret=? WHERE id=?").bind(secret, id),
          db
            .prepare("UPDATE device_sessions SET deleted_at=? WHERE scale_id=?")
            .bind(now(), id),
        ]);
        return go(
          `/scales#scale-${id}`,
          "Scale secret replaced; sessions invalidated",
        );
      }
      if (purpose === "fixture") {
        const endpoint = formText(form, "endpoint");
        const column = {
          screen: "screen_response",
          summary: "summary_response",
          weather: "weather_response",
        }[endpoint as "screen" | "summary" | "weather"];
        if (!column) throw new Error("Unknown fixture endpoint");
        const raw = validatedFixture(formText(form, "fixture"), endpoint);
        await run(db, `UPDATE scales SET ${column}=? WHERE id=?`, raw, id);
        return go(`/scales#scale-${id}`, `${endpoint} fixture saved`);
      }
      if (purpose === "roster_snapshot") {
        await run(
          db,
          "UPDATE scales SET roster_snapshot=?,roster_enabled=0 WHERE id=?",
          validatedRoster(formText(form, "roster_snapshot")),
          id,
        );
        return go(
          `/scales#scale-${id}`,
          "Roster baseline saved; one-shot delivery remains off",
        );
      }
      return new Response("Bad Request", { status: 400 });
    }
    if (path === "/users/import-withings/confirm") {
      const id = formInteger(form, "scale_id");
      const scale = await one(db, "SELECT * FROM scales WHERE id=?", id);
      const stored = await reviewedCapture(db, id);
      if (
        !scale ||
        !stored ||
        stored.capture.mac !== scale.mac ||
        !equal(stored.digest, formText(form, "capture_digest"))
      )
        throw new Error("Reviewed capture has changed");
      const selected = form.getAll("user_ids").map(Number);
      if (
        selected.some(
          (value) => !stored.capture.sp!.users.some((u) => u.id === value),
        )
      )
        throw new Error("Unknown imported user");
      await importCaptureUsers(
        db,
        scale,
        stored,
        false,
        null,
        new Set(selected),
      );
      return go("/users", "Selected users imported; existing users retained");
    }

    if (path === "/users") {
      const user = parsedUser(form);
      const highest = await one<{ id: number }>(
        db,
        "SELECT COALESCE(MAX(id),0)+1 AS id FROM users",
      );
      const id = Math.max(
        highest?.id ?? 1,
        Number((await setting(db, "next_local_user_id")) ?? "1"),
      );
      if (id > 2147483647) throw new Error("No user IDs remain");
      const memberships = await updateMemberships(db, id, user.scales);
      await db.batch([
        db
          .prepare(
            "INSERT INTO users(id,name,short_name,height_cm,age_years,birth_date,sex,reference_weight_kg,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
          )
          .bind(
            id,
            user.name,
            user.short,
            user.height,
            user.age,
            user.dob,
            user.sex,
            user.weight,
            now(),
          ),
        ...memberships,
        saveSetting(db, "next_local_user_id", String(id + 1)),
      ]);
      return go("/users", `User ${user.name} added as stable scale ID ${id}`);
    }
    const userDelete = /^\/users\/(\d+)\/delete$/.exec(path);
    if (userDelete) {
      const id = Number(userDelete[1]);
      const user = await one(db, "SELECT id FROM users WHERE id=?", id);
      if (!user) return new Response("Not Found", { status: 404 });
      const statements: D1PreparedStatement[] = [
        db
          .prepare(
            "UPDATE scales SET roster_enabled=0 WHERE id IN (SELECT scale_id FROM scale_users WHERE user_id=?)",
          )
          .bind(id),
      ];
      for (const scale of await rows(
        db,
        "SELECT id,roster_snapshot FROM scales WHERE roster_snapshot IS NOT NULL",
      )) {
        const roster = parseJson(scale.roster_snapshot);
        if (!Array.isArray(roster))
          throw new Error("Saved scale roster is malformed");
        const updated = roster.filter((entry: Row) => entry.id !== id);
        if (updated.length !== roster.length)
          statements.push(
            db
              .prepare(
                "UPDATE scales SET roster_snapshot=?,roster_enabled=0 WHERE id=?",
              )
              .bind(JSON.stringify(updated), scale.id),
          );
      }
      for (const reading of await rows(
        db,
        "SELECT id,candidate_ids FROM readings WHERE candidate_ids LIKE ?",
        `%${id}%`,
      )) {
        const candidates = parseJson(reading.candidate_ids);
        if (!Array.isArray(candidates))
          throw new Error("Reading candidate list is malformed");
        const updated = candidates.filter(
          (candidate: number) => candidate !== id,
        );
        if (updated.length !== candidates.length)
          statements.push(
            db
              .prepare("UPDATE readings SET candidate_ids=? WHERE id=?")
              .bind(JSON.stringify(updated), reading.id),
          );
      }
      statements.push(
        db
          .prepare(
            "UPDATE readings SET user_id=NULL,attribution='unassigned' WHERE user_id=?",
          )
          .bind(id),
        db.prepare("UPDATE events SET user_id=NULL WHERE user_id=?").bind(id),
        db.prepare("DELETE FROM scale_users WHERE user_id=?").bind(id),
        db.prepare("DELETE FROM users WHERE id=?").bind(id),
        saveSetting(
          db,
          "next_local_user_id",
          String(
            Math.max(
              Number((await setting(db, "next_local_user_id")) ?? "1"),
              id + 1,
            ),
          ),
        ),
      );
      await db.batch(statements);
      return go(
        "/users",
        "User deleted locally; their readings are now unassigned",
      );
    }
    const userPath = /^\/users\/(\d+)$/.exec(path);
    if (userPath) {
      const id = Number(userPath[1]);
      if (!(await one(db, "SELECT id FROM users WHERE id=?", id)))
        return new Response("Not Found", { status: 404 });
      if (formText(form, "purpose") === "retire") {
        await db.batch([
          db.prepare("UPDATE users SET active=0 WHERE id=?").bind(id),
          db.prepare("DELETE FROM scale_users WHERE user_id=?").bind(id),
        ]);
        await queueRosterEdits(db, id);
        return go("/users", "User retired; historical readings remain");
      }
      const user = parsedUser(form);
      const memberships = await updateMemberships(db, id, user.scales);
      await db.batch([
        db
          .prepare(
            "UPDATE users SET name=?,short_name=?,height_cm=?,age_years=?,birth_date=?,sex=?,reference_weight_kg=? WHERE id=?",
          )
          .bind(
            user.name,
            user.short,
            user.height,
            user.age,
            user.dob,
            user.sex,
            user.weight,
            id,
          ),
        ...memberships,
      ]);
      await queueRosterEdits(db, id);
      return go(
        "/users",
        "User updated; supported WBS06 roster edits will be sent on its next connection",
      );
    }
    const readingAssign = /^\/readings\/(\d+)\/assign$/.exec(path);
    if (readingAssign) {
      const id = Number(readingAssign[1]),
        userId = formInteger(form, "user_id");
      if (!(await one(db, "SELECT id FROM users WHERE id=?", userId)))
        throw new Error("Unknown user");
      const [result] = await db.batch([
        db
          .prepare(
            "UPDATE readings SET user_id=?,attribution='manual' WHERE id=? AND user_id IS NULL",
          )
          .bind(userId, id),
        refreshRecognitionWeight(db, userId),
      ]);
      if (result.meta.changes !== 1)
        throw new Error("Reading is missing or already assigned");
      await queueRosterEdits(db, userId);
      return go("/readings", "Reading assigned");
    }
    const readingDelete = /^\/readings\/(\d+)\/delete$/.exec(path);
    if (readingDelete) {
      const result = await run(
        db,
        "DELETE FROM readings WHERE id=? AND user_id IS NULL",
        Number(readingDelete[1]),
      );
      return go(
        "/readings",
        result.meta.changes
          ? "Unassigned reading deleted"
          : "Reading is missing or assigned",
      );
    }
    return new Response("Not Found", { status: 404 });
  } catch (error) {
    const destination = path.startsWith("/scales")
      ? "/scales"
      : path.startsWith("/users")
        ? "/users"
        : path.startsWith("/readings")
          ? "/readings"
          : path;
    return go(destination, safeError(error));
  }
}
