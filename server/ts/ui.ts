/** Small server-rendered views shared by the Worker and local Node entrypoint. */
import { scaleModel } from "./models.ts";
import { METRICS, storedMeasures, type Metric } from "./metrics.ts";
import { WEB_APP_VERSION } from "./version.ts";
type Row = Record<string, any>;
export const escapeHtml = (value: unknown): string =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ]!,
  );
const e = escapeHtml;
const n = (value: unknown) => Number(value ?? 0);
export const hidden = (csrf: string) =>
  `<input type="hidden" name="_csrf" value="${e(csrf)}">`;
const option = (value: string | number, label: string, selected: unknown) =>
  `<option value="${e(value)}"${String(value) === String(selected) ? " selected" : ""}>${e(label)}</option>`;
export const timeLabel = (value: unknown): string => {
  const date = new Date(n(value) * 1000);
  return Number.isFinite(date.valueOf()) && n(value) > 0
    ? e(
        new Intl.DateTimeFormat("en-GB", {
          dateStyle: "medium",
          timeStyle: "short",
        }).format(date),
      )
    : "Unknown";
};
export function weightLabel(row: Row, unit: string): string {
  if (row.weight_value == null || row.weight_unit == null) return "—";
  const kg = n(row.weight_value) * 10 ** n(row.weight_unit);
  if (unit === "lb") return `${(kg * 2.2046226218487757).toFixed(1)} lb`;
  if (unit === "st") {
    const tenths = Math.round(kg * 2.2046226218487757 * 10);
    return `${Math.floor(tenths / 140)} st ${((tenths % 140) / 10).toFixed(1)} lb`;
  }
  return `${kg.toFixed(2)} kg`;
}
function metricPicker(
  metrics: Metric[],
  selected: number,
  name = "metric",
  selections: Record<string, number> = {},
): string {
  if (metrics.length < 2) return "";
  const preserved = Object.entries(selections)
    .filter(([key]) => key !== name)
    .map(
      ([key, value]) =>
        `<input type="hidden" name="${e(key)}" value="${e(value)}">`,
    )
    .join("");
  return `<form method="get" class="metric-picker">${preserved}<label>Measurement<select name="${e(name)}" data-submit-on-change>${metrics.map((m) => option(m.type, m.label, selected)).join("")}</select></label><button class="secondary" type="submit">Show</button></form>`;
}
function metricLabel(row: Row, type: number, weightUnit: string): string {
  if (type === 1) return weightLabel(row, weightUnit);
  const matches = storedMeasures(row).filter((m) => m.type === type);
  if (!matches.length) return "—";
  const metric = METRICS.find((v) => v.type === type)!;
  return matches
    .map((m) => {
      const value =
        metric.unit === "kg"
          ? weightLabel(
              { weight_value: m.value, weight_unit: m.unit },
              weightUnit,
            )
          : `${new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2 }).format(m.value * 10 ** m.unit)}${metric.unit === "index" ? "" : ` ${e(metric.unit)}`}`;
      return matches.length > 1
        ? `${value} (Position ${e(m.position ?? "Unspecified")})`
        : value;
    })
    .join("; ");
}
function metricTitle(type: number): string {
  return METRICS.find((m) => m.type === type)?.label ?? "Weight";
}
export function layout(
  title: string,
  body: string,
  csrf: string,
  loggedIn: boolean,
  notice = "",
  active = "",
): string {
  const links = [
    ["/", "Dashboard"],
    ["/readings", "Readings"],
    ["/scales", "Scales"],
    ["/users", "Users"],
    ["/sync", "Sync"],
    ["/settings", "Settings"],
    ["/firmware", "Firmware Bridge"],
  ];
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>${e(title)} · YourOwnWeigh</title><link rel="icon" href="/favicon.png" type="image/png">
    <meta name="csrf-token" content="${e(csrf)}"><link rel="stylesheet" href="/app.css?v=${WEB_APP_VERSION}"><script src="/app.js?v=${WEB_APP_VERSION}" defer></script></head><body>
    <nav><a class="brand" href="/" aria-label="YourOwnWeigh"><img src="/favicon.png" width="36" height="36" alt=""><strong>YOW</strong></a>${
      loggedIn
        ? links
            .map(
              ([url, label]) =>
                `<a href="${url}"${active === url ? ' aria-current="page"' : ""}>${label}</a>`,
            )
            .join("") +
          `<form action="/logout" method="post">${hidden(csrf)}<button>Sign Out</button></form>`
        : ""
    }</nav>
    ${notice ? `<p class="flash" role="status">${e(notice)}</p>` : ""}<main>${body}</main><footer class="site-footer"><span>YourOwnWeigh · Web App v${e(WEB_APP_VERSION)}</span><a href="https://github.com/TomAnthony/YourOwnWeigh" target="_blank" rel="noopener noreferrer">GitHub</a></footer></body></html>`;
}
export function setupPage(
  csrf: string,
  bootstrapRequired = false,
  unlocked = false,
): string {
  if (bootstrapRequired && !unlocked)
    return `<section><h1>Welcome To YourOwnWeigh</h1><p>Enter the bootstrap token shown by the setup command.</p><form method="post">${hidden(csrf)}<input type="hidden" name="step" value="bootstrap"><label>Bootstrap Token<input name="bootstrap_token" type="password" required autocomplete="off"></label><button>Continue</button></form></section>`;
  return `<section><h1>Set Your Password</h1><p>Protect your dashboard and Sync API. Passwords must contain at least eight characters.</p><form method="post">${hidden(csrf)}<input type="hidden" name="step" value="password"><label>Admin Password<input name="password" type="password" minlength="8" required autocomplete="new-password"></label><label>Confirm Admin Password<input name="confirm" type="password" minlength="8" required autocomplete="new-password"></label>
    <label><input type="checkbox" name="separate_sync" value="1" data-toggle="setup-sync-fields"> Set Alternative Password For Sync API</label><div id="setup-sync-fields" hidden><label>Sync API Password<input name="sync_password" type="password" minlength="8" autocomplete="new-password"></label><label>Confirm Sync API Password<input name="sync_confirm" type="password" minlength="8" autocomplete="new-password"></label></div><button>Create Household</button></form></section>`;
}
export function loginPage(csrf: string): string {
  return `<section><h1>Sign In</h1><form method="post">${hidden(csrf)}<label>Admin Password<input name="password" type="password" required></label><button>Sign In</button></form></section>`;
}
function readingTime(row: Row): string {
  const trusted = row.time_quality === "trusted";
  return `${timeLabel(trusted ? row.meastime : row.first_received_at)}${trusted ? "" : '<span class="hint">Received Time; Device Date Unverified</span>'}`;
}
function healthSyncStatus(row: Row): string {
  if (!row.user_id || row.weight_value == null)
    return '<span class="muted">—</span>';
  const acknowledgedAt = Number(row.health_sync_acknowledged_at);
  if (!Number.isFinite(acknowledgedAt) || acknowledgedAt <= 0)
    return '<span class="muted">Not Acknowledged</span>';
  return `<span class="badge">Acknowledged</span><time class="hint" datetime="${new Date(acknowledgedAt * 1000).toISOString()}">${timeLabel(acknowledgedAt)}</time>`;
}
export function dashboardPage(
  cards: Array<{
    user: Row;
    readings: Row[];
    metrics?: Metric[];
    metric?: number;
  }>,
  unit: string,
): string {
  const selections = Object.fromEntries(
    cards.map(({ user, metric = 1 }) => [`metric_${user.id}`, metric]),
  );
  return `<section class="page-heading"><div><h1>Dashboard</h1></div><a class="button secondary" href="/readings">View All Readings</a></section>
  ${
    cards.length
      ? `<div class="cards">${cards
          .map(
            ({
              user,
              readings,
              metrics = [METRICS[0]],
              metric = 1,
            }) => `<section class="card"><div class="section-heading"><div>
    <h2><a href="/users/${e(user.id)}/readings">${e(user.name)}</a></h2></div><a href="/users/${e(user.id)}/readings">All Readings →</a></div>
    ${metricPicker(metrics, metric, `metric_${user.id}`, selections)}
    ${
      readings.length
        ? `<p class="metric">${metricLabel(readings[0], metric, unit)}</p><div class="wide"><table><thead><tr><th>When</th><th>${e(metricTitle(metric))}</th><th>Scale</th></tr></thead><tbody>
    ${readings.map((r) => `<tr data-reading-id="${e(r.id)}"><td>${readingTime(r)}</td><td>${metricLabel(r, metric, unit)}</td><td>${e(r.scale_label)}</td></tr>`).join("")}</tbody></table></div>`
        : '<p class="empty">No readings recorded yet.</p>'
    }</section>`,
          )
          .join("")}</div>`
      : '<section><p class="empty">No users have been added yet.</p><a class="button" href="/firmware">Add Your First Scale</a></section>'
  }`;
}
export function readingsPage(
  readings: Row[],
  users: Row[],
  unit: string,
  csrf: string,
  metrics: Metric[] = [METRICS[0]],
  metric = 1,
): string {
  return `<section><h1>Readings</h1>${metricPicker(metrics, metric)}
    ${
      readings.length
        ? `<div class="wide"><table><thead><tr><th>When</th><th>${e(metricTitle(metric))}</th><th>User</th><th>Scale</th>${metric === 1 ? "<th>Health Sync</th>" : ""}<th>Actions</th></tr></thead><tbody>
    ${readings
      .map(
        (r) =>
          `<tr data-reading-id="${e(r.id)}"><td>${readingTime(r)}</td><td>${metricLabel(r, metric, unit)}</td><td>${r.user_id ? `<a href="/users/${e(r.user_id)}/readings">${e(r.user_name)}</a>` : '<span class="badge warn">Unassigned</span>'}</td><td>${e(r.scale_label)}</td>${metric === 1 ? `<td>${healthSyncStatus(r)}</td>` : ""}<td>${
            r.user_id
              ? "—"
              : `<div class="actions">${users.length ? `<form class="inline-form" action="/readings/${e(r.id)}/assign" method="post">${hidden(csrf)}<label class="hint">Assign To</label><select name="user_id" required><option value="">Choose User</option>${users.map((u) => option(u.id, u.name, "")).join("")}</select><button>Assign</button></form>` : ""}
      <form action="/readings/${e(r.id)}/delete" method="post" data-confirm="Delete this unassigned reading permanently?">${hidden(csrf)}<button class="danger">Delete</button></form></div>`
          }</td></tr>`,
      )
      .join("")}
    </tbody></table></div>`
        : '<p class="empty">No readings recorded yet.</p>'
    }</section>`;
}
export function userReadingsPage(
  user: Row,
  readings: Row[],
  unit: string,
  metrics: Metric[] = [METRICS[0]],
  metric = 1,
): string {
  return `<section><a href="/">← Dashboard</a><h1>${e(user.name)} Readings</h1>${metricPicker(metrics, metric)}
    ${
      readings.length
        ? `<div class="wide"><table><thead><tr><th>When</th><th>${e(metricTitle(metric))}</th><th>Scale</th><th>Attribution</th>${metric === 1 ? "<th>Health Sync</th>" : ""}</tr></thead><tbody>${readings
            .map(
              (r) =>
                `<tr><td>${readingTime(r)}</td><td>${metricLabel(r, metric, unit)}</td><td>${e(r.scale_label)}</td><td>${e(r.attribution)}</td>${metric === 1 ? `<td>${healthSyncStatus(r)}</td>` : ""}</tr>`,
            )
            .join("")}</tbody></table></div>`
        : '<p class="empty">No readings recorded for this user.</p>'
    }</section>`;
}
function userFields(
  user: Row | null,
  scales: Row[],
  members: Set<number>,
): string {
  return `<div class="device-grid"><label>Name<input name="name" value="${e(user?.name)}" required></label><label>Short Name<input name="short_name" value="${e(user?.short_name)}" maxlength="3" required></label>
    <label>Height (cm)<input name="height_cm" type="number" step="1" value="${e(user?.height_cm)}" required></label>
    <label>Date of Birth<input name="birth_date" type="date" value="${e(user?.birth_date)}"></label>
    <label>Approximate Age (if DOB unknown)<input name="age_years" type="number" step="0.1" value="${e(user?.age_years)}"></label>
    <label>Sex<select name="sex">${option(0, "Male", user?.sex ?? 0)}${option(1, "Female", user?.sex ?? 0)}</select></label>
    <label>Recognition Weight (kg)<input name="reference_weight_kg" type="number" step="any" value="${e(user?.reference_weight_kg)}" title="Updated from the latest assigned weigh-in and sent on the scale’s next Wi-Fi sync." required></label></div>
    <fieldset><legend>Scales</legend>${scales.map((s) => `<label><input type="checkbox" name="scales" value="${e(s.id)}"${members.has(s.id) ? " checked" : ""}> ${e(s.label)}</label>`).join("")}</fieldset>`;
}
export function usersPage(
  users: Row[],
  scales: Row[],
  memberships: Map<number, Set<number>>,
  csrf: string,
  preview?: {
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
  },
  fetchMode?: "verified-tls" | "plaintext-http",
  importScaleId?: number,
): string {
  return `<section><div class="page-heading"><div><h1>Users</h1></div><div class="actions"><button type="button" class="secondary" data-open-dialog="import-users-dialog">Import From Withings</button><button type="button" data-open-dialog="add-user-dialog">Add User</button></div></div>
    ${
      preview
        ? `<dialog id="import-preview-dialog" data-auto-open><button class="dialog-close" type="button" data-close-dialog>×</button><h2>Import Users From ${e(preview.scale.label)}</h2><p>${preview.settingsStatus === "configured" || scaleModel(preview.scale.model)?.classicGates ? "Device settings are ready." : "Device settings import is incomplete; use Finish Device Import on Scales to retry."} Existing users are retained.</p>
      <form action="/users/import-withings/confirm" method="post">${hidden(csrf)}<input type="hidden" name="scale_id" value="${e(preview.scale.id)}"><input type="hidden" name="capture_digest" value="${e(preview.digest)}">
      ${preview.users.length ? preview.users.map((u) => `<label><input type="checkbox" name="user_ids" value="${e(u.id)}" checked> ${e(u.fn || u.sn)} · ${e(u.sn)} · ID ${e(u.id)}</label>`).join("") : "<p>All users are already in this household.</p>"}
      <div class="dialog-actions"><button>Import Selected Users</button><button type="button" class="secondary" data-close-dialog>Later</button></div></form></dialog>`
        : ""
    }
    ${
      users.length
        ? `<div class="wide"><table><thead><tr><th>Name</th><th>Short Name</th><th>Height</th><th>Age / DOB</th><th>Sex</th><th>Scales</th><th>Status</th><th></th></tr></thead><tbody>
    ${users
      .map(
        (
          u,
        ) => `<tr><td>${e(u.name)}</td><td>${e(u.short_name)}</td><td>${Math.round(n(u.height_cm))} cm</td><td>${e(u.birth_date || u.age_years)}</td><td>${u.sex === 0 ? "Male" : "Female"}</td>
      <td>${scales
        .filter((s) => memberships.get(u.id)?.has(s.id))
        .map((s) => e(s.label))
        .join(
          ", ",
        )}</td><td>${u.active ? "Active" : "Retired"}</td><td><button type="button" class="secondary" data-open-dialog="edit-user-${e(u.id)}">Edit</button></td></tr>`,
      )
      .join("")}</tbody></table></div>`
        : '<p class="empty">No users have been added yet.</p>'
    }</section>
    <dialog id="import-users-dialog"${importScaleId ? " data-auto-open" : ""}><button type="button" class="dialog-close" data-close-dialog>×</button><h2>Import From Withings</h2>
      <p>Read the selected scale’s existing users and settings over verified HTTPS. New users are shown for selection; existing local users are preserved.</p>
      ${fetchMode ? `<form action="/users/fetch-withings" method="post">${hidden(csrf)}<label>Scale<select name="scale_id" required><option value="">Choose Scale</option>${scales.map((s) => option(s.id, s.label, importScaleId ?? "")).join("")}</select></label><button>Fetch From Withings</button></form>` : "<p>Withings import is unavailable on this server.</p>"}</dialog>
    <dialog id="add-user-dialog"><button type="button" class="dialog-close" data-close-dialog>×</button><h2>Add User</h2><form action="/users" method="post">${hidden(csrf)}${userFields(null, scales, new Set())}<button>Save User</button></form></dialog>
    ${users
      .map(
        (
          u,
        ) => `<dialog id="edit-user-${e(u.id)}"><button type="button" class="dialog-close" data-close-dialog>×</button><h2>Edit ${e(u.name)}</h2>
      <form action="/users/${e(u.id)}" method="post">${hidden(csrf)}${userFields(u, scales, memberships.get(u.id) ?? new Set())}<div class="dialog-actions"><button>Save User</button></div></form>
      <div class="dialog-actions"><form action="/users/${e(u.id)}" method="post">${hidden(csrf)}<input type="hidden" name="purpose" value="retire"><button class="secondary">Retire User</button></form>
      <form action="/users/${e(u.id)}/delete" method="post" data-confirm="Delete this user locally? Their readings will become unassigned.">${hidden(csrf)}<button class="danger">Delete User</button></form></div></dialog>`,
      )
      .join("")}`;
}
