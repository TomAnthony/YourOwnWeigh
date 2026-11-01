/** Shared scale ingestion, with model-specific authentication/responses. */
import { ws30MD5 } from "./ws30_md5.ts";
import { scaleModel } from "./models.ts";
import { validateMetricJson } from "./metrics.ts";
import {
  backfillRecognitionWeights,
  refreshRecognitionWeight,
} from "./recognition.ts";
import {
  firmwareObservation,
  sessionFirmware,
} from "./firmware_observation.ts";

interface ScaleEnv {
  DB: D1Database;
}

type ScaleRow = {
  id: number;
  model: string;
  mac: string;
  secret: string;
  settings_ready: number;
  screen_response: string | null;
  summary_response: string | null;
  weather_response: string | null;
  roster_enabled: number;
  roster_snapshot: string | null;
  time_zone: string | null;
  goff: number;
  dst: number;
  ngoff: number;
  feature_mask: number;
  beta_ws: number;
  temp_code: number;
  weight_code: number;
};

const NONCE_TTL = 120;
// browser_auth_limits also holds browser/Sync API counters with a ten-minute window.
const AUTH_LIMIT_RETENTION = 600;
const MAX_LIVE_CHALLENGES = 1024;
const MAX_ONCE_PER_PEER = 32;
const SESSION_TTL = 3600;
const MAX_BODY = 128 * 1024;
const MAC_RE = /^(?:(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}|[0-9a-f]{12})$/i;
const SID_RE = /^[0-9a-f]{24}$/i;
const encoder = new TextEncoder();

const now = () => Math.floor(Date.now() / 1000);

/** Screen IDs from a roster `cs` field ("2,1,3"; "" means none). Returns null
 * when the value is missing or malformed, so callers can reject it. */
export function screenIds(cs: unknown): number[] | null {
  if (cs === "") return [];
  if (typeof cs !== "string" || !/^\d{1,5}(,\d{1,5}){0,31}$/.test(cs))
    return null;
  return cs.split(",").map(Number);
}
function randomHex(bytes: number): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(bytes)), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

function canonicalMac(value: string): string | null {
  return MAC_RE.test(value.trim())
    ? value.replace(/[:-]/g, "").toUpperCase()
    : null;
}

async function sha256(value: string): Promise<string> {
  const digest = new Uint8Array(
    await crypto.subtle.digest("SHA-256", encoder.encode(value)),
  );
  return Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join(
    "",
  );
}

/** SHA-1 hex, solely for the WS-50's existing device challenge protocol. */
async function sha1Hex(value: string): Promise<string> {
  const digest = new Uint8Array(
    await crypto.subtle.digest("SHA-1", encoder.encode(value)),
  );
  return Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join(
    "",
  );
}

function sameHex(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let difference = 0;
  for (let i = 0; i < a.length; i++)
    difference |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return difference === 0;
}

function json(payload: object, status = 200): Response {
  return Response.json(payload, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function error(code: 400 | 403, reason: string): Response {
  return json({ status: code, error: reason }, code);
}

async function parameters(
  request: Request,
  url: URL,
): Promise<URLSearchParams | Response> {
  const advertised = Number(request.headers.get("Content-Length"));
  if (Number.isFinite(advertised) && advertised > MAX_BODY)
    return json({ error: "body too large" }, 413);
  const reader = request.body?.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  if (reader) {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_BODY) {
        await reader.cancel();
        return json({ error: "body too large" }, 413);
      }
      chunks.push(value);
    }
  }
  const bytes = new Uint8Array(total);
  let cursor = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, cursor);
    cursor += chunk.byteLength;
  }
  const params = new URLSearchParams(url.search);
  for (const [key, value] of new URLSearchParams(
    new TextDecoder().decode(bytes),
  )) {
    params.append(key, value);
  }
  return params;
}

function audit(
  db: D1Database,
  scaleId: number | null,
  endpoint: string,
  outcome: string,
  detail: string | null = null,
): D1PreparedStatement {
  return db
    .prepare(
      "INSERT INTO sync_audit(scale_id,endpoint,outcome,received_at,detail) VALUES(?,?,?,?,?)",
    )
    .bind(scaleId, endpoint, outcome, now(), detail);
}

function peer(request: Request): string {
  // Both production entrypoints replace or strip client-supplied peer headers.
  return (
    request.headers.get("X-YOW-Peer-IP") ??
    request.headers.get("CF-Connecting-IP") ??
    "unknown"
  );
}

async function limitKey(request: Request, purpose: string): Promise<string> {
  return sha256(`${purpose}:${peer(request)}`);
}

async function once(
  env: ScaleEnv,
  request: Request,
  params: URLSearchParams,
): Promise<Response> {
  if (params.get("action") !== "get") return error(400, "unsupported action");
  const timestamp = now();
  const key = await limitKey(request, "scale-once");
  const cutoff = timestamp - NONCE_TTL;
  await env.DB.batch([
    env.DB.prepare("DELETE FROM browser_auth_limits WHERE window_start<?").bind(
      timestamp - AUTH_LIMIT_RETENTION,
    ),
    env.DB.prepare(
      "INSERT INTO browser_auth_limits(key,window_start,attempts) VALUES(?,?,1) " +
        "ON CONFLICT(key) DO UPDATE SET attempts=CASE WHEN window_start<? THEN 1 ELSE attempts+1 END," +
        "window_start=CASE WHEN window_start<? THEN excluded.window_start ELSE window_start END",
    ).bind(key, timestamp, cutoff, cutoff),
    env.DB.prepare(
      "DELETE FROM challenges WHERE issued_at<? OR consumed_at IS NOT NULL",
    ).bind(cutoff),
  ]);
  const budget = await env.DB.prepare(
    "SELECT attempts FROM browser_auth_limits WHERE key=?",
  )
    .bind(key)
    .first<{ attempts: number }>();
  if ((budget?.attempts ?? 0) > MAX_ONCE_PER_PEER)
    return json({ error: "too many challenges" }, 429);
  const nonce = randomHex(12);
  // The capacity check and insert are one SQL statement, so concurrent callers
  // cannot force out a live nonce while a scale computes its session hash.
  const issued = await env.DB.prepare(
    "INSERT INTO challenges(nonce,issued_at) SELECT ?,? " +
      "WHERE (SELECT COUNT(*) FROM challenges)<?",
  )
    .bind(nonce, timestamp, MAX_LIVE_CHALLENGES)
    .run();
  if (issued.meta.changes !== 1)
    return json({ error: "challenge capacity reached" }, 429);
  return json({ status: 0, body: { once: nonce } });
}

function offsetAt(formatter: Intl.DateTimeFormat, timestamp: number): number {
  const label = formatter
    .formatToParts(new Date(timestamp * 1000))
    .find((part) => part.type === "timeZoneName")?.value;
  if (label === "GMT" || label === "UTC") return 0;
  const match = /^GMT([+-])(\d{1,2})(?::(\d{2}))?$/.exec(label ?? "");
  if (!match) throw new Error("Unsupported time zone offset");
  return (
    (match[1] === "+" ? 1 : -1) *
    (Number(match[2]) * 3600 + Number(match[3] ?? 0) * 60)
  );
}

/** Current offset and next transition, matching the local ctp wire shape. */
export function zoneTriplet(
  name: string,
  timestamp = now(),
): { goff: number; dst: number; ngoff: number } {
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone: name,
    timeZoneName: "shortOffset",
  });
  const goff = offsetAt(formatter, timestamp);
  let previous = timestamp;
  // Weekly probes find the normal next DST transition cheaply. At the first
  // changed probe, binary search to the exact second without a second timezone implementation in the bridge.
  for (let week = 1; week <= 157; week++) {
    const probe = timestamp + week * 7 * 86400;
    if (offsetAt(formatter, probe) !== goff) {
      let lo = previous;
      let hi = probe;
      while (lo + 1 < hi) {
        const mid = Math.floor((lo + hi) / 2);
        if (offsetAt(formatter, mid) === goff) lo = mid;
        else hi = mid;
      }
      return { goff, dst: hi, ngoff: offsetAt(formatter, hi) };
    }
    previous = probe;
  }
  return { goff, dst: 0, ngoff: goff };
}

function timeSettings(scale: ScaleRow): {
  goff: number;
  dst: number;
  ngoff: number;
} {
  if (!scale.time_zone)
    return { goff: scale.goff, dst: scale.dst, ngoff: scale.ngoff };
  return zoneTriplet(scale.time_zone);
}

function ageFromDOB(value: string): number {
  const born = Date.parse(`${value}T00:00:00Z`);
  if (!Number.isFinite(born)) throw new Error("Invalid birth date");
  const today = new Date();
  const midnight = Date.UTC(
    today.getUTCFullYear(),
    today.getUTCMonth(),
    today.getUTCDate(),
  );
  return Math.round(((midnight - born) / 86400000 / 365.2425) * 10) / 10;
}

/** Overlay explicit local edits while preserving people skipped at import.
 * The vendor wire uses metres for ht; the UI/database use centimetres. */
export async function roster(
  env: ScaleEnv,
  scale: ScaleRow,
): Promise<object[]> {
  if (scale.model === "WBS13") {
    const { results } = await env.DB.prepare(
      "SELECT u.* FROM users u JOIN scale_users su ON su.user_id=u.id WHERE su.scale_id=? AND u.active=1 ORDER BY su.rank,u.id",
    )
      .bind(scale.id)
      .all<Record<string, any>>();
    if (!results.length || results.length > 8)
      throw new Error("Choose one to eight users for this scale");
    await backfillRecognitionWeights(env.DB, results);
    return results.map((u) => {
      const age = u.birth_date ? ageFromDOB(u.birth_date) : u.age_years;
      const composition =
        age >= 18 &&
        age <= 99 &&
        u.height_cm >= 90 &&
        u.height_cm <= 249 &&
        u.reference_weight_kg >= 29 &&
        u.reference_weight_kg <= 270;
      return {
        id: u.id,
        sn: u.short_name.toUpperCase(),
        fn:
          u.name
            .normalize("NFKD")
            .replace(/[^ -~]/g, "")
            .slice(0, 16) || u.short_name,
        ht: u.height_cm / 100,
        agt: age,
        sx: u.sex,
        wt: u.reference_weight_kg,
        fm: 3,
        cr: u.reference_weight_at ?? u.created_at,
        att: 0,
        cs: composition ? "2,1,3" : "2",
      };
    });
  }
  if (!scale.roster_snapshot) throw new Error("Roster baseline missing");
  const baseline = JSON.parse(scale.roster_snapshot) as Array<
    Record<string, any>
  >;
  if (
    !Array.isArray(baseline) ||
    baseline.length > 8 ||
    new Set(baseline.map((u) => u.id)).size !== baseline.length
  )
    throw new Error("Invalid roster baseline");
  const { results } = await env.DB.prepare(
    "SELECT u.*,su.scale_id AS membership FROM users u LEFT JOIN scale_users su ON su.user_id=u.id AND su.scale_id=?",
  )
    .bind(scale.id)
    .all<Record<string, any>>();
  const byId = new Map(results.map((u) => [u.id, u]));
  await backfillRecognitionWeights(env.DB, results);
  const users = baseline.flatMap((entry) => {
    const user = byId.get(entry.id);
    if (!user) return [entry]; // Not imported locally: keep the scale's person.
    if (!user.active || !user.membership) return [];
    return [
      {
        ...entry,
        id: user.id,
        sn: user.short_name,
        fn: user.name,
        ht: user.height_cm / 100,
        agt: user.birth_date ? ageFromDOB(user.birth_date) : user.age_years,
        sx: user.sex,
        wt: user.reference_weight_kg,
        ...(user.reference_weight_at !== null
          ? { cr: user.reference_weight_at }
          : {}),
      },
    ];
  });
  if (!users.length) throw new Error("An empty roster has not been qualified");
  return users;
}

async function authenticationFailure(
  env: ScaleEnv,
  scale: ScaleRow | null,
  request: Request,
): Promise<Response> {
  if (scale) {
    const timestamp = now();
    const key = await limitKey(request, `scale-session-${scale.id}`);
    await env.DB.batch([
      env.DB.prepare(
        "DELETE FROM browser_auth_limits WHERE window_start<?",
      ).bind(timestamp - AUTH_LIMIT_RETENTION),
      env.DB.prepare(
        "INSERT INTO browser_auth_limits(key,window_start,attempts) " +
          "VALUES(?,?,1) ON CONFLICT(key) DO UPDATE SET " +
          "attempts=CASE WHEN window_start<? THEN 1 ELSE attempts+1 END," +
          "window_start=CASE WHEN window_start<? THEN excluded.window_start ELSE window_start END",
      ).bind(key, timestamp, timestamp - 300, timestamp - 300),
    ]);
  }
  return error(403, "session authentication failed");
}

async function newSession(
  env: ScaleEnv,
  request: Request,
  params: URLSearchParams,
): Promise<Response> {
  const auth = params.get("auth") ?? "";
  const submitted = params.get("hash") ?? "";
  const mac = canonicalMac(auth);
  if (!mac) return authenticationFailure(env, null, request);
  const scale = await env.DB.prepare("SELECT * FROM scales WHERE mac=?")
    .bind(mac)
    .first<ScaleRow>();
  // Select the protocol from the enrolled device, never from a caller-supplied model.
  const model = scaleModel(scale?.model);
  const classic = model?.transport === "classic";
  const validHash = model
    ? new RegExp(`^[0-9a-f]{${model.hashLength}}$`, "i").test(submitted) &&
      (model.hashParam === null
        ? !params.has("hashmethod") && !params.has("method")
        : params.get(model.hashParam.name) === model.hashParam.value)
    : false;
  if (!validHash) return authenticationFailure(env, scale, request);
  if (scale) {
    const key = await limitKey(request, `scale-session-${scale.id}`);
    const failure = await env.DB.prepare(
      "SELECT window_start,attempts FROM browser_auth_limits WHERE key=?",
    )
      .bind(key)
      .first<{ window_start: number; attempts: number }>();
    if (
      failure &&
      failure.attempts >= 10 &&
      failure.window_start >= now() - 300
    ) {
      return error(403, "session authentication failed");
    }
  }
  let matched: string | null = null;
  if (scale) {
    const { results } = await env.DB.prepare(
      "SELECT nonce FROM challenges WHERE consumed_at IS NULL AND issued_at>=? " +
        "ORDER BY issued_at DESC LIMIT 1024",
    )
      .bind(now() - NONCE_TTL)
      .all<{ nonce: string }>();
    for (const challenge of results ?? []) {
      const material = `${auth}:${scale.secret}:${challenge.nonce}`;
      const expected =
        model?.hash === "md5"
          ? ws30MD5(material)
          : model?.hash === "sha1"
            ? await sha1Hex(material)
            : await sha256(material);
      if (sameHex(expected, submitted.toLowerCase())) {
        matched = challenge.nonce;
        break;
      }
    }
  }
  if (!scale || !matched) return authenticationFailure(env, scale, request);

  const reportedMask = params.get("feature_mask") ?? "";
  const reportedMfgid = params.get("mfgid") ?? "";
  const observations: D1PreparedStatement[] = [];
  if (/^\d{1,10}$/.test(reportedMfgid) && Number(reportedMfgid) <= 0x7fffffff) {
    observations.push(
      env.DB.prepare("UPDATE scales SET reported_mfgid=? WHERE id=?").bind(
        Number(reportedMfgid),
        scale.id,
      ),
    );
  }
  if (/^\d{1,10}$/.test(reportedMask) && Number(reportedMask) <= 0x7fffffff) {
    observations.push(
      env.DB.prepare(
        "UPDATE scales SET reported_feature_mask=?,reported_feature_at=? WHERE id=?",
      ).bind(Number(reportedMask), now(), scale.id),
    );
  }
  if (
    !classic &&
    (!scale.settings_ready ||
      (!["WBS13", "WBS04"].includes(scale.model) &&
        (!scale.screen_response || !scale.summary_response)))
  ) {
    await env.DB.batch([
      ...observations,
      audit(
        env.DB,
        scale.id,
        "session",
        "unconfigured",
        "device profile import incomplete",
      ),
    ]);
    return json(
      {
        status: 503,
        error: "scale settings or display fixtures not configured",
      },
      503,
    );
  }
  let users: object[] | undefined;
  if (!classic && (scale.roster_enabled || scale.model === "WBS13")) {
    try {
      users = await roster(env, scale);
    } catch {
      await env.DB.batch([
        ...observations,
        audit(
          env.DB,
          scale.id,
          "session",
          "unconfigured",
          "roster baseline mismatch",
        ),
      ]);
      return json({ status: 503, error: "roster baseline mismatch" }, 503);
    }
  }
  let ctp: { goff: number; dst: number; ngoff: number } | undefined;
  try {
    // WS-30 retains its own settings unless a time zone is explicitly supplied.
    // Its clock is still synchronized by syp.utc on every session.
    if (!classic || scale.time_zone) ctp = timeSettings(scale);
  } catch {
    await env.DB.batch([
      ...observations,
      audit(env.DB, scale.id, "session", "unconfigured", "invalid time zone"),
    ]);
    return json({ status: 503, error: "scale time zone not configured" }, 503);
  }

  const token = randomHex(12);
  const timestamp = now();
  const issued = env.DB.prepare(
    "INSERT INTO device_sessions(token,scale_id,expires_at) " +
      "SELECT ?,?,? FROM challenges WHERE nonce=? AND consumed_at IS NULL AND issued_at>=?",
  ).bind(
    token,
    scale.id,
    timestamp + SESSION_TTL,
    matched,
    timestamp - NONCE_TTL,
  );
  const present = "EXISTS (SELECT 1 FROM device_sessions WHERE token=?)";
  const statements: D1PreparedStatement[] = [
    issued,
    env.DB.prepare(
      `UPDATE challenges SET consumed_at=? WHERE nonce=? AND consumed_at IS NULL AND ${present}`,
    ).bind(timestamp, matched, token),
    env.DB.prepare(
      `DELETE FROM browser_auth_limits WHERE key=? AND ${present}`,
    ).bind(await limitKey(request, `scale-session-${scale.id}`), token),
    env.DB.prepare(
      `UPDATE scales SET last_session_at=? WHERE id=? AND ${present}`,
    ).bind(timestamp, scale.id, token),
  ];
  const reportedVersion = sessionFirmware(params, scale.model);
  if (reportedVersion !== null) {
    statements.push(
      firmwareObservation(
        env.DB,
        scale.id,
        reportedVersion,
        timestamp,
        "wifi",
        token,
      ),
    );
  }
  if (!classic && scale.roster_enabled) {
    statements.push(
      env.DB.prepare(
        `UPDATE scales SET roster_enabled=0,roster_last_sent_at=? WHERE id=? AND ${present}`,
      ).bind(timestamp, scale.id, token),
    );
  }
  statements.push(
    ...observations,
    env.DB.prepare(
      "INSERT INTO sync_audit(scale_id,endpoint,outcome,received_at) " +
        `SELECT ?,'session','opened',? WHERE ${present}`,
    ).bind(scale.id, timestamp, token),
  );
  const result = await env.DB.batch(statements);
  if (result[0].meta.changes !== 1 || result[1].meta.changes !== 1) {
    return error(403, "session authentication failed");
  }

  const body: Record<string, unknown> = {
    sessionid: token,
    syp: { utc: now() },
  };
  if (ctp) body.ctp = ctp;
  if (scale.model === "WBS13")
    body.ind = { stp: 0, fm: scale.feature_mask, ws: scale.beta_ws };
  else if (!classic)
    body.ind = {
      stp: 0,
      fm: scale.feature_mask,
      ws: scale.beta_ws,
      tmp: scale.temp_code,
      w: scale.weight_code,
    };
  if (users) body.sp = { users };
  return json({ status: 0, body });
}

async function deleteSession(
  env: ScaleEnv,
  params: URLSearchParams,
): Promise<Response> {
  const token = params.get("sessionid") ?? "";
  if (!SID_RE.test(token)) return error(403, "invalid session");
  const row = await env.DB.prepare(
    "SELECT ds.deleted_at,s.id AS scale_id FROM device_sessions ds " +
      "JOIN scales s ON s.id=ds.scale_id WHERE ds.token=? AND ds.expires_at>?",
  )
    .bind(token, now())
    .first<{ deleted_at: number | null; scale_id: number }>();
  if (!row) return error(403, "invalid session");
  if (row.deleted_at === null) {
    await env.DB.batch([
      env.DB.prepare(
        "UPDATE device_sessions SET deleted_at=? WHERE token=? AND deleted_at IS NULL",
      ).bind(now(), token),
      audit(env.DB, row.scale_id, "session", "closed"),
    ]);
  } else {
    await audit(env.DB, row.scale_id, "session", "close retry").run();
  }
  return json({ status: 0 });
}

async function session(
  env: ScaleEnv,
  request: Request,
  params: URLSearchParams,
): Promise<Response> {
  if (params.get("action") === "new") return newSession(env, request, params);
  if (params.get("action") === "delete") return deleteSession(env, params);
  return error(400, "unsupported action");
}

async function requireDeviceSession(
  env: ScaleEnv,
  params: URLSearchParams,
  endpoint: string,
): Promise<ScaleRow | null> {
  const token = params.get("sessionid") ?? "";
  if (!SID_RE.test(token)) return null;
  const scale = await env.DB.prepare(
    "SELECT s.* FROM device_sessions ds JOIN scales s ON s.id=ds.scale_id " +
      "WHERE ds.token=? AND ds.deleted_at IS NULL AND ds.expires_at>?",
  )
    .bind(token, now())
    .first<ScaleRow>();
  return scale;
}

async function fixture(
  env: ScaleEnv,
  params: URLSearchParams,
  endpoint: "screen" | "summary" | "weather",
  expectedAction: string,
): Promise<Response> {
  if (params.get("action") !== expectedAction)
    return error(400, "unsupported action");
  const scale = await requireDeviceSession(env, params, endpoint);
  if (!scale) return error(403, "invalid session");
  if (scale.model === "WBS13" || scale.model === "WBS04") {
    // WBS04 (Body Cardio) builds its screen config dynamically from the roster
    // `cs` screen IDs, like WBS13, instead of a captured Withings fixture. This
    // supplies the heart-rate / PWV / vascular-age screens so the scale runs the
    // full measurement sequence rather than weight only.
    let body: object = endpoint === "summary" ? [] : {};
    if (endpoint === "screen") {
      const users = (await roster(env, scale)) as Array<{
        id: number;
        cs?: unknown;
      }>;
      body = {
        device: [],
        user: users.map((u) => ({
          userid: u.id,
          // A missing or malformed `cs` (older snapshot, manual edit or
          // restored backup) falls back to the weight screen instead of
          // failing every screen request. An explicit empty selection (the
          // user turned every screen off) is preserved as-is.
          screens: (screenIds(u.cs) ?? [2]).map((id, i) => ({
            id,
            src: 1,
            embid: id,
            rk: i + 1,
          })),
        })),
      };
    }
    await audit(env.DB, scale.id, endpoint, "served").run();
    return json({ status: 0, body });
  }
  if (endpoint === "weather") {
    // No live provider is configured. Never replay a captured forecast: it may
    // describe an old date/location. An empty series supplies no forecast data.
    // The device may retain its last display until its own cache expires.
    await audit(env.DB, scale.id, endpoint, "suppressed").run();
    return json({ status: 0, body: { series: [] } });
  }
  if (scaleModel(scale.model)?.classicGates && endpoint === "summary") {
    // No historic summary is supplied yet. The captured WS-30 schema is an
    // array; an empty array leaves no graph entries to apply.
    await audit(env.DB, scale.id, endpoint, "served").run();
    return json({ status: 0, body: [] });
  }
  const column = `${endpoint}_response` as keyof ScaleRow;
  const raw = scale[column];
  if (typeof raw !== "string" || !raw) {
    await audit(env.DB, scale.id, endpoint, "unconfigured").run();
    return json(
      { status: 503, error: `${endpoint} fixture not configured` },
      503,
    );
  }
  await audit(env.DB, scale.id, endpoint, "served").run();
  return new Response(raw, {
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function sorted(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sorted);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, item]) => [key, sorted(item)]),
    );
  }
  return value;
}

const stableJson = (value: unknown) => JSON.stringify(sorted(value));

async function event(
  env: ScaleEnv,
  params: URLSearchParams,
): Promise<Response> {
  if (params.get("action") !== "fire") return error(400, "unsupported action");
  const eventType = Number(params.get("type"));
  const epoch = Number(params.get("epoch"));
  const uidString = params.get("userid");
  const userId = uidString === null ? null : Number(uidString);
  const raw = params.get("data") ?? "{}";
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return error(400, "invalid event payload");
  }
  if (
    !params.has("type") ||
    !params.has("epoch") ||
    !Number.isInteger(eventType) ||
    eventType < 0 ||
    eventType >= 2 ** 31 ||
    !Number.isInteger(epoch) ||
    epoch < 946684800 ||
    epoch > 4102444800 ||
    (userId !== null &&
      (!Number.isInteger(userId) || userId < 1 || userId > 2147483647)) ||
    encoder.encode(raw).length > 16000
  ) {
    return error(400, "invalid event payload");
  }
  const scale = await requireDeviceSession(env, params, "event");
  if (!scale) return error(403, "invalid session");
  const digest = await sha256(
    stableJson({
      scale: scale.mac,
      type: eventType,
      epoch,
      user_id: userId,
      data: parsed,
    }),
  );
  await env.DB.batch([
    env.DB.prepare(
      "INSERT INTO events(scale_id,event_type,epoch,user_id,data_json,payload_hash,received_at) " +
        "VALUES(?,?,?,?,?,?,?) ON CONFLICT(payload_hash) DO UPDATE SET attempts=attempts+1",
    ).bind(scale.id, eventType, epoch, userId, raw, digest, now()),
    audit(env.DB, scale.id, "event", "committed"),
  ]);
  return json({ status: 0 });
}

type MeasureItem = {
  value: number;
  type: number;
  unit: number;
  [key: string]: unknown;
};
type ParsedGroup = {
  index: number;
  meastime: number;
  measures: MeasureItem[];
  weight: MeasureItem | undefined;
  raw: Record<string, unknown>;
};

function integer(value: unknown): number {
  if (typeof value === "number" && Number.isSafeInteger(value)) return value;
  if (
    typeof value === "string" &&
    /^[+-]?\d+$/.test(value) &&
    Number.isSafeInteger(Number(value))
  ) {
    return Number(value);
  }
  throw new Error("invalid integer");
}

function parseGroups(params: URLSearchParams): {
  mac: string;
  attribstatus: number;
  devtype: number;
  category: number;
  candidates: number[];
  groups: ParsedGroup[];
} {
  const mac = canonicalMac(params.get("macaddress") ?? "");
  if (!mac) throw new Error("invalid MAC");
  const attribstatus = integer(params.get("attribstatus") ?? "0");
  const devtype = integer(params.get("devtype") ?? "0");
  const category = integer(params.get("category") ?? "0");
  const candidates = params.getAll("userid").map(integer);
  if (attribstatus < -(2 ** 31) || attribstatus >= 2 ** 31) {
    throw new Error("invalid attribution status");
  }
  if (
    candidates.length > 8 ||
    candidates.some((id) => id < 1 || id > 2147483647)
  ) {
    throw new Error("invalid candidate IDs");
  }
  const payload = JSON.parse(params.get("measuregrps") ?? "");
  validateMetricJson(payload);
  const source = payload.measuregrps;
  if (!Array.isArray(source) || source.length < 1 || source.length > 32) {
    throw new Error("invalid measure groups");
  }
  const groups = source.map(
    (group: Record<string, unknown>, index: number): ParsedGroup => {
      const meastime = integer(group.meastime);
      if (meastime < 0 || meastime > 0xffffffff)
        throw new Error("invalid timestamp");
      if (
        !Array.isArray(group.measures) ||
        group.measures.length < 1 ||
        group.measures.length > 32
      ) {
        throw new Error("invalid measures");
      }
      const measures = group.measures.map(
        (item: Record<string, unknown>): MeasureItem => {
          const normalized: MeasureItem = {
            ...item,
            value: integer(item.value),
            type: integer(item.type),
            unit: integer(item.unit),
          };
          if (normalized.unit < -12 || normalized.unit > 12)
            throw new Error("invalid unit");
          if (normalized.value < -(2 ** 31) || normalized.value >= 2 ** 31) {
            throw new Error("invalid measure value");
          }
          if (
            normalized.type < 1 ||
            normalized.type > 0xffff ||
            (normalized.position !== undefined &&
              (!Number.isSafeInteger(normalized.position) ||
                Number(normalized.position) < 0 ||
                Number(normalized.position) > 0xffff))
          )
            throw new Error("invalid metric metadata");
          return normalized;
        },
      );
      const weight = measures.find((item: MeasureItem) => item.type === 1);
      if (weight && weight.value <= 0) throw new Error("invalid weight");
      if (
        group.algo !== undefined &&
        (!Number.isSafeInteger(group.algo) ||
          Number(group.algo) < 0 ||
          Number(group.algo) > 0xffffffff)
      )
        throw new Error("invalid metric metadata");
      return {
        index,
        meastime,
        measures,
        weight,
        raw: { ...group, meastime, measures },
      };
    },
  );
  if (devtype !== 1 || category !== 1)
    throw new Error("unexpected device/category");
  return { mac, attribstatus, devtype, category, candidates, groups };
}

async function invalidMeasure(
  env: ScaleEnv,
  scaleId: number,
  params: URLSearchParams,
  reason: string,
): Promise<Response> {
  const groups = params.get("measuregrps") ?? "";
  const diagnostic = {
    macaddress: params.get("macaddress")?.slice(0, 32) ?? "",
    measuregrps_prefix: groups.slice(0, 256),
    measuregrps_length: groups.length,
    measuregrps_sha256: await sha256(groups),
  };
  await env.DB.batch([
    env.DB.prepare(
      "INSERT INTO measure_rejections(received_at,validation_stage,reason,form_without_session) " +
        "VALUES(?,?,?,?)",
    ).bind(now(), "measure groups", reason, JSON.stringify(diagnostic)),
    audit(env.DB, scaleId, "measure", "invalid", `measure groups: ${reason}`),
  ]);
  return error(400, "invalid measurement payload");
}

async function measure(
  env: ScaleEnv,
  params: URLSearchParams,
): Promise<Response> {
  if (params.get("action") !== "batchstore")
    return error(400, "unsupported action");
  const scale = await requireDeviceSession(env, params, "measure");
  if (!scale) return error(403, "invalid session");
  let parsed: ReturnType<typeof parseGroups>;
  try {
    parsed = parseGroups(params);
  } catch (cause) {
    const known = new Set([
      "invalid attribution status",
      "invalid candidate IDs",
      "invalid measure groups",
      "invalid timestamp",
      "invalid measures",
      "invalid unit",
      "invalid measure value",
      "invalid metric metadata",
      "invalid weight",
      "unexpected device/category",
    ]);
    const reason =
      cause instanceof Error && known.has(cause.message)
        ? cause.message
        : "ValueError";
    return invalidMeasure(env, scale.id, params, reason);
  }
  if (scale.mac !== parsed.mac) {
    await audit(
      env.DB,
      scale.id,
      "measure",
      "rejected",
      "MAC/session mismatch",
    ).run();
    return error(403, "invalid session");
  }

  let userId: number | null = null;
  let attribution = "unassigned";
  if (parsed.candidates.length === 1) {
    const found = await env.DB.prepare(
      "SELECT 1 AS present FROM users WHERE id=?",
    )
      .bind(parsed.candidates[0])
      .first<{ present: number }>();
    if (found) {
      userId = parsed.candidates[0];
      attribution = "device";
    }
  } else if (parsed.candidates.length > 1) {
    attribution = "ambiguous";
  }

  const timestamp = now();
  const digests: string[] = [];
  for (const group of parsed.groups) {
    const metadata = Object.fromEntries(
      Object.entries(group.raw).filter(
        ([key, value]) =>
          key !== "meastime" &&
          key !== "measures" &&
          !(key === "algo" && value === 0),
      ),
    );
    digests.push(
      await sha256(
        stableJson({
          mac: parsed.mac,
          candidate_ids: parsed.candidates,
          attribstatus: parsed.attribstatus,
          devtype: parsed.devtype,
          category: parsed.category,
          index: group.index,
          meastime: group.meastime,
          measures: group.measures,
          // Keep the established weight-only hash (including algo:0 uploads).
          // Nonzero/extended metadata distinguishes richer groups without
          // creating duplicates when older scales retry after this upgrade.
          ...(Object.keys(metadata).length ? { group_metadata: metadata } : {}),
        }),
      ),
    );
  }
  const placeholders = digests.map(() => "?").join(",");
  const { results: previous } = await env.DB.prepare(
    `SELECT payload_hash FROM readings WHERE payload_hash IN (${placeholders})`,
  )
    .bind(...digests)
    .all<{ payload_hash: string }>();
  const seen = new Set((previous ?? []).map((row) => row.payload_hash));
  let newGroups = 0;
  let duplicateGroups = 0;
  const statements: D1PreparedStatement[] = [];
  for (const [position, group] of parsed.groups.entries()) {
    const digest = digests[position];
    if (seen.has(digest)) duplicateGroups++;
    else newGroups++;
    seen.add(digest);
    const quality =
      group.meastime >= 946684800 && group.meastime <= timestamp + 86400
        ? "trusted"
        : "untrusted";
    statements.push(
      env.DB.prepare(
        "INSERT INTO readings(scale_id,user_id,attribution,candidate_ids,attribstatus,meastime," +
          "time_quality,weight_value,weight_unit,measures_json,group_json,payload_hash,first_received_at,last_received_at) " +
          "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(payload_hash) DO UPDATE SET " +
          "attempts=attempts+1,last_received_at=excluded.last_received_at",
      ).bind(
        scale.id,
        userId,
        attribution,
        JSON.stringify(parsed.candidates),
        parsed.attribstatus,
        group.meastime,
        quality,
        group.weight?.value ?? null,
        group.weight?.unit ?? null,
        JSON.stringify(group.measures),
        JSON.stringify(group.raw),
        digest,
        timestamp,
        timestamp,
      ),
    );
  }
  const safeForm = {
    macaddress: params.get("macaddress") ?? "",
    userid: parsed.candidates,
    devtype: parsed.devtype,
    category: parsed.category,
    attribstatus: parsed.attribstatus,
    measuregrps: params.get("measuregrps") ?? "",
  };
  statements.push(
    audit(
      env.DB,
      scale.id,
      "measure",
      "committed",
      `new=${newGroups};duplicates=${duplicateGroups}`,
    ),
    env.DB.prepare(
      "INSERT INTO measure_attempts(scale_id,received_at,payload_sha256," +
        "form_without_session,new_groups,duplicate_groups) VALUES(?,?,?,?,?,?)",
    ).bind(
      scale.id,
      timestamp,
      await sha256(stableJson(safeForm)),
      JSON.stringify(safeForm),
      newGroups,
      duplicateGroups,
    ),
  );
  // D1.batch commits all rows together. Never ACK a measure after a partial write.
  if (userId !== null)
    statements.push(refreshRecognitionWeight(env.DB, userId));
  await env.DB.batch(statements);
  if (scaleModel(scale.model)?.classicGates) {
    return json({
      status: 0,
      body: [{ updatetime: timestamp, measuregrps: [] }],
    });
  }
  return json({ status: 0 });
}

/** Minimal update/feature replies qualified by the WBS13 HTTP capture. */
async function wbs13Query(
  env: ScaleEnv,
  params: URLSearchParams,
  path: string,
): Promise<Response> {
  const scale = await requireDeviceSession(env, params, path);
  if (!scale || scale.model !== "WBS13") return error(403, "invalid session");
  const action = params.get("action");
  let body: object;
  if (
    path === "/v2/measure" &&
    action === "getlastupdate" &&
    params.get("objects") === "devices"
  )
    body = { devices: [] };
  else if (path === "/v2/feature" && action === "getbydevice")
    body = { device_features: [], user_features: [] };
  else if (path === "/v2/screen" && action === "getcontentbydeviceid")
    body = { user_screens: [] };
  else return error(400, "unsupported action");
  await audit(env.DB, scale.id, path, "served").run();
  return json({ status: 0, body });
}

export async function handleScaleRequest(
  request: Request,
  env: ScaleEnv,
): Promise<Response | null> {
  const url = new URL(request.url);
  const paths = [
    "/once",
    "/session",
    "/cgi-bin/once",
    "/cgi-bin/session",
    "/cgi-bin/measure",
    "/v2/screen",
    "/v2/summary",
    "/v2/weather",
    "/v2/event",
    "/measure",
    "/v2/measure",
    "/v2/feature",
  ];
  if (request.method !== "POST" || !paths.includes(url.pathname)) return null;
  const params = await parameters(request, url);
  if (params instanceof Response) return params;
  const cgi = url.pathname.startsWith("/cgi-bin/");
  const base = cgi ? url.pathname.slice("/cgi-bin".length) : url.pathname;
  if (base === "/once") return once(env, request, params);
  if (base === "/session") return session(env, request, params);
  if (
    ["/v2/measure", "/v2/feature"].includes(base) ||
    (base === "/v2/screen" && params.get("action") === "getcontentbydeviceid")
  )
    return wbs13Query(env, params, base);
  if (base === "/v2/screen")
    return fixture(env, params, "screen", "getbydeviceid");
  if (base === "/v2/summary")
    return fixture(env, params, "summary", "getforscale");
  if (base === "/v2/weather")
    return fixture(env, params, "weather", "getforecast");
  if (base === "/measure") return measure(env, params);
  return event(env, params);
}
