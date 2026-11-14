/** Small server-rendered views shared by the Worker and local Node entrypoint. */
import { scaleModel } from "./models.ts";
import { METRICS, storedMeasures, type Metric } from "./metrics.ts";
import { WEB_APP_VERSION } from "./version.ts";
import {
  LOCALES,
  translateMessage,
  translator,
  type Language,
  type MessageKey,
  type Translate,
} from "./i18n.ts";
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
export const timeLabel = (
  value: unknown,
  language: Language = "en",
): string => {
  const date = new Date(n(value) * 1000);
  return Number.isFinite(date.valueOf()) && n(value) > 0
    ? e(
        new Intl.DateTimeFormat(LOCALES[language], {
          dateStyle: "medium",
          timeStyle: "short",
        }).format(date),
      )
    : e(translator(language)("time.unknown"));
};
/** Battery percentage at or below which a scale is shown as needing attention. */
export const LOW_BATTERY = 20;
const SCALE_ICON =
  '<svg class="icon-scale" viewBox="0 0 16 16" aria-hidden="true"><rect x=".75" y=".75" width="14.5" height="14.5" rx="3.5" fill="none" stroke="currentColor" stroke-width="1.5"/><rect x="5" y="3.5" width="6" height="3" rx="1" fill="currentColor"/></svg>';
function batteryIcon(level: number): string {
  const fill = Math.max(2, (14 * level) / 100).toFixed(1);
  return `<svg class="icon-battery" viewBox="0 0 24 12" aria-hidden="true"><rect x=".75" y=".75" width="18.5" height="10.5" rx="2.5" fill="none" stroke="currentColor" stroke-width="1.5"/><rect x="21" y="3.5" width="2.5" height="5" rx="1" fill="currentColor"/><rect x="3" y="3" width="${fill}" height="6" rx="1" fill="currentColor"/></svg>`;
}
/** Stored battery level of a scale row, or null when never reported. */
export function batteryOf(scale: Row): number | null {
  const level = scale.battery_level;
  return typeof level === "number" && level >= 0 && level <= 100 ? level : null;
}
/** What to do about a low battery, worded for the model's power source. */
export function batteryAction(
  model: unknown,
  language: Language = "en",
): string {
  return translator(language)(
    scaleModel(String(model ?? ""))?.rechargeable
      ? "battery.chargeSoon"
      : "battery.replace",
  );
}
/** Dashboard row: one badge per scale that has reported a battery level. */
export function scaleBatteries(
  scales: Row[],
  language: Language = "en",
): string {
  const t = translator(language);
  const badges = scales
    .map((s) => {
      const level = batteryOf(s);
      if (level === null) return "";
      const low = level <= LOW_BATTERY;
      return `<span class="badge scale-battery${low ? " warn" : ""}" title="${e(t("battery.reportedTitle", { time: timeLabel(s.last_session_at, language) }))}">${SCALE_ICON}<span>${e(s.label)}</span>${batteryIcon(level)}<span>${level} %</span>${low ? `<span>· ${e(batteryAction(s.model, language))}</span>` : ""}</span>`;
    })
    .join("");
  return badges ? `<div class="scale-batteries">${badges}</div>` : "";
}
const decimal = (value: number, digits: number, language: Language) =>
  new Intl.NumberFormat(LOCALES[language], {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    useGrouping: false,
  }).format(value);
/** Translated name of a metric. */
export const metricName = (metric: Metric, t: Translate = translator("en")) =>
  t(`metric.${metric.key}` as MessageKey);
export function weightLabel(
  row: Row,
  unit: string,
  language: Language = "en",
): string {
  if (row.weight_value == null || row.weight_unit == null) return "—";
  const kg = n(row.weight_value) * 10 ** n(row.weight_unit);
  if (unit === "lb")
    return `${decimal(kg * 2.2046226218487757, 1, language)} lb`;
  if (unit === "st") {
    const tenths = Math.round(kg * 2.2046226218487757 * 10);
    return `${Math.floor(tenths / 140)} st ${decimal((tenths % 140) / 10, 1, language)} lb`;
  }
  return `${decimal(kg, 2, language)} kg`;
}
function metricPicker(
  metrics: Metric[],
  selected: number,
  name = "metric",
  selections: Record<string, number> = {},
  t: Translate = translator("en"),
): string {
  if (metrics.length < 2) return "";
  const preserved = Object.entries(selections)
    .filter(([key]) => key !== name)
    .map(
      ([key, value]) =>
        `<input type="hidden" name="${e(key)}" value="${e(value)}">`,
    )
    .join("");
  return `<form method="get" class="metric-picker">${preserved}<label>${e(t("metric.picker"))}<select name="${e(name)}" data-submit-on-change>${metrics.map((m) => option(m.type, metricName(m, t), selected)).join("")}</select></label><button class="secondary" type="submit">${e(t("metric.show"))}</button></form>`;
}
function metricLabel(
  row: Row,
  type: number,
  weightUnit: string,
  language: Language = "en",
): string {
  const t = translator(language);
  if (type === 1) return weightLabel(row, weightUnit, language);
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
              language,
            )
          : `${new Intl.NumberFormat(LOCALES[language], { maximumFractionDigits: 2 }).format(m.value * 10 ** m.unit)}${metric.unit === "index" ? "" : ` ${e(metric.unit)}`}`;
      return matches.length > 1
        ? `${value} (${e(t("reading.position", { position: m.position ?? t("reading.positionUnspecified") }))})`
        : value;
    })
    .join("; ");
}
function metricTitle(type: number, t: Translate = translator("en")): string {
  return metricName(METRICS.find((m) => m.type === type) ?? METRICS[0], t);
}
export function layout(
  title: string,
  body: string,
  csrf: string,
  loggedIn: boolean,
  notice = "",
  active = "",
  language: Language = "en",
): string {
  const t = translator(language);
  const links = [
    ["/", t("nav.dashboard")],
    ["/readings", t("nav.readings")],
    ["/scales", t("nav.scales")],
    ["/users", t("nav.users")],
    ["/sync", t("nav.sync")],
    ["/settings", t("nav.settings")],
    ["/firmware", t("nav.firmware")],
  ];
  return `<!doctype html><html lang="${language}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>${e(title)} · YourOwnWeigh</title><link rel="icon" href="/favicon.png" type="image/png">
    <meta name="csrf-token" content="${e(csrf)}"><link rel="stylesheet" href="/app.css?v=${WEB_APP_VERSION}"><script src="/app.js?v=${WEB_APP_VERSION}" defer></script></head><body>
    <nav><a class="brand" href="/" aria-label="YourOwnWeigh"><img src="/favicon.png" width="36" height="36" alt=""><strong>YOW</strong></a>${
      loggedIn
        ? links
            .map(
              ([url, label]) =>
                `<a href="${url}"${active === url ? ' aria-current="page"' : ""}>${e(label)}</a>`,
            )
            .join("") +
          `<form action="/logout" method="post">${hidden(csrf)}<button>${e(t("nav.signOut"))}</button></form>`
        : ""
    }</nav>
    ${notice ? `<p class="flash" role="status">${e(translateMessage(notice, language))}</p>` : ""}<main>${body}</main><footer class="site-footer"><span>YourOwnWeigh · Web App v${e(WEB_APP_VERSION)}</span><a href="https://github.com/TomAnthony/YourOwnWeigh" target="_blank" rel="noopener noreferrer">GitHub</a></footer></body></html>`;
}
export function setupPage(
  csrf: string,
  bootstrapRequired = false,
  unlocked = false,
  t: Translate = translator("en"),
): string {
  const T = (key: MessageKey) => e(t(key));
  if (bootstrapRequired && !unlocked)
    return `<section><h1>${T("setup.welcome")}</h1><p>${T("setup.tokenIntro")}</p><form method="post">${hidden(csrf)}<input type="hidden" name="step" value="bootstrap"><label>${T("setup.token")}<input name="bootstrap_token" type="password" required autocomplete="off"></label><button>${T("common.continue")}</button></form></section>`;
  return `<section><h1>${T("setup.passwordTitle")}</h1><p>${T("setup.passwordIntro")}</p><form method="post">${hidden(csrf)}<input type="hidden" name="step" value="password"><label>${T("auth.adminPassword")}<input name="password" type="password" minlength="8" required autocomplete="new-password"></label><label>${T("setup.confirmAdmin")}<input name="confirm" type="password" minlength="8" required autocomplete="new-password"></label>
    <label><input type="checkbox" name="separate_sync" value="1" data-toggle="setup-sync-fields"> ${T("sync.alternativePassword")}</label><div id="setup-sync-fields" hidden><label>${T("setup.syncPassword")}<input name="sync_password" type="password" minlength="8" autocomplete="new-password"></label><label>${T("setup.syncConfirm")}<input name="sync_confirm" type="password" minlength="8" autocomplete="new-password"></label></div><button>${T("setup.create")}</button></form></section>`;
}
export function loginPage(
  csrf: string,
  t: Translate = translator("en"),
): string {
  return `<section><h1>${e(t("auth.signIn"))}</h1><form method="post">${hidden(csrf)}<label>${e(t("auth.adminPassword"))}<input name="password" type="password" required></label><button>${e(t("auth.signIn"))}</button></form></section>`;
}
function readingTime(row: Row, language: Language = "en"): string {
  const trusted = row.time_quality === "trusted";
  return `${timeLabel(trusted ? row.meastime : row.first_received_at, language)}${trusted ? "" : `<span class="hint">${e(translator(language)("reading.receivedTime"))}</span>`}`;
}
function healthSyncStatus(row: Row, language: Language = "en"): string {
  const t = translator(language);
  if (!row.user_id || row.weight_value == null)
    return '<span class="muted">—</span>';
  const acknowledgedAt = Number(row.health_sync_acknowledged_at);
  if (!Number.isFinite(acknowledgedAt) || acknowledgedAt <= 0)
    return `<span class="muted">${e(t("health.notAcknowledged"))}</span>`;
  return `<span class="badge">${e(t("health.acknowledged"))}</span><time class="hint" datetime="${new Date(acknowledgedAt * 1000).toISOString()}">${timeLabel(acknowledgedAt, language)}</time>`;
}
/** Translated attribution status; unknown values are shown as stored. */
function attributionLabel(value: unknown, t: Translate): string {
  const key = `attribution.${String(value)}` as MessageKey;
  const text = t(key);
  return text === key ? String(value ?? "") : text;
}
export function dashboardPage(
  cards: Array<{
    user: Row;
    readings: Row[];
    metrics?: Metric[];
    metric?: number;
  }>,
  unit: string,
  scales: Row[] = [],
  language: Language = "en",
): string {
  const t = translator(language);
  const selections = Object.fromEntries(
    cards.map(({ user, metric = 1 }) => [`metric_${user.id}`, metric]),
  );
  return `<section class="page-heading"><div><h1>${e(t("nav.dashboard"))}</h1></div><a class="button secondary" href="/readings">${e(t("dashboard.viewAllReadings"))}</a></section>
  ${scaleBatteries(scales, language)}${
    cards.length
      ? `<div class="cards">${cards
          .map(
            ({
              user,
              readings,
              metrics = [METRICS[0]],
              metric = 1,
            }) => `<section class="card"><div class="section-heading"><div>
    <h2><a href="/users/${e(user.id)}/readings">${e(user.name)}</a></h2></div><a href="/users/${e(user.id)}/readings">${e(t("dashboard.allReadings"))}</a></div>
    ${metricPicker(metrics, metric, `metric_${user.id}`, selections, t)}
    ${
      readings.length
        ? `<p class="metric">${metricLabel(readings[0], metric, unit, language)}</p><div class="wide"><table><thead><tr><th>${e(t("dashboard.when"))}</th><th>${e(metricTitle(metric, t))}</th><th>${e(t("dashboard.scale"))}</th></tr></thead><tbody>
    ${readings.map((r) => `<tr data-reading-id="${e(r.id)}"><td>${readingTime(r, language)}</td><td>${metricLabel(r, metric, unit, language)}</td><td>${e(r.scale_label)}</td></tr>`).join("")}</tbody></table></div>`
        : `<p class="empty">${e(t("dashboard.noReadings"))}</p>`
    }</section>`,
          )
          .join("")}</div>`
      : `<section><p class="empty">${e(t("dashboard.noUsers"))}</p><a class="button" href="/firmware">${e(t("dashboard.addFirstScale"))}</a></section>`
  }`;
}
export function readingsPage(
  readings: Row[],
  users: Row[],
  unit: string,
  csrf: string,
  metrics: Metric[] = [METRICS[0]],
  metric = 1,
  language: Language = "en",
): string {
  const t = translator(language);
  const T = (key: MessageKey) => e(t(key));
  return `<section><h1>${T("nav.readings")}</h1>${metricPicker(metrics, metric, "metric", {}, t)}
    ${
      readings.length
        ? `<div class="wide"><table><thead><tr><th>${T("dashboard.when")}</th><th>${e(metricTitle(metric, t))}</th><th>${T("readings.user")}</th><th>${T("dashboard.scale")}</th>${metric === 1 ? `<th>${T("readings.healthSync")}</th>` : ""}<th>${T("readings.actions")}</th></tr></thead><tbody>
    ${readings
      .map(
        (r) =>
          `<tr data-reading-id="${e(r.id)}"><td>${readingTime(r, language)}</td><td>${metricLabel(r, metric, unit, language)}</td><td>${r.user_id ? `<a href="/users/${e(r.user_id)}/readings">${e(r.user_name)}</a>` : `<span class="badge warn">${T("readings.unassigned")}</span>`}</td><td>${e(r.scale_label)}</td>${metric === 1 ? `<td>${healthSyncStatus(r, language)}</td>` : ""}<td>${
            r.user_id
              ? "—"
              : `<div class="actions">${users.length ? `<form class="inline-form" action="/readings/${e(r.id)}/assign" method="post">${hidden(csrf)}<label class="hint">${T("readings.assignTo")}</label><select name="user_id" required><option value="">${T("readings.chooseUser")}</option>${users.map((u) => option(u.id, u.name, "")).join("")}</select><button>${T("readings.assign")}</button></form>` : ""}
      <form action="/readings/${e(r.id)}/delete" method="post" data-confirm="${T("readings.confirmDelete")}">${hidden(csrf)}<button class="danger">${T("common.delete")}</button></form></div>`
          }</td></tr>`,
      )
      .join("")}
    </tbody></table></div>`
        : `<p class="empty">${T("dashboard.noReadings")}</p>`
    }</section>`;
}
export function userReadingsPage(
  user: Row,
  readings: Row[],
  unit: string,
  metrics: Metric[] = [METRICS[0]],
  metric = 1,
  language: Language = "en",
): string {
  const t = translator(language);
  const T = (key: MessageKey) => e(t(key));
  return `<section><a href="/">${T("userReadings.back")}</a><h1>${e(t("userReadings.title", { name: String(user.name ?? "") }))}</h1>${metricPicker(metrics, metric, "metric", {}, t)}
    ${
      readings.length
        ? `<div class="wide"><table><thead><tr><th>${T("dashboard.when")}</th><th>${e(metricTitle(metric, t))}</th><th>${T("dashboard.scale")}</th><th>${T("userReadings.attribution")}</th>${metric === 1 ? `<th>${T("readings.healthSync")}</th>` : ""}</tr></thead><tbody>${readings
            .map(
              (r) =>
                `<tr><td>${readingTime(r, language)}</td><td>${metricLabel(r, metric, unit, language)}</td><td>${e(r.scale_label)}</td><td>${e(attributionLabel(r.attribution, t))}</td>${metric === 1 ? `<td>${healthSyncStatus(r, language)}</td>` : ""}</tr>`,
            )
            .join("")}</tbody></table></div>`
        : `<p class="empty">${T("userReadings.none")}</p>`
    }</section>`;
}
function userFields(
  user: Row | null,
  scales: Row[],
  members: Set<number>,
  t: Translate,
): string {
  const T = (key: MessageKey) => e(t(key));
  return `<div class="device-grid"><label>${T("users.name")}<input name="name" value="${e(user?.name)}" required></label><label>${T("users.shortName")}<input name="short_name" value="${e(user?.short_name)}" maxlength="3" required></label>
    <label>${T("users.heightCm")}<input name="height_cm" type="number" step="1" value="${e(user?.height_cm)}" required></label>
    <label>${T("users.birthDate")}<input name="birth_date" type="date" value="${e(user?.birth_date)}"></label>
    <label>${T("users.approxAge")}<input name="age_years" type="number" step="0.1" value="${e(user?.age_years)}"></label>
    <label>${T("users.sex")}<select name="sex">${option(0, t("users.male"), user?.sex ?? 0)}${option(1, t("users.female"), user?.sex ?? 0)}</select></label>
    <label>${T("users.recognitionWeight")}<input name="reference_weight_kg" type="number" step="any" value="${e(user?.reference_weight_kg)}" title="${T("users.recognitionHint")}" required></label></div>
    <fieldset><legend>${T("nav.scales")}</legend>${scales.map((s) => `<label><input type="checkbox" name="scales" value="${e(s.id)}"${members.has(s.id) ? " checked" : ""}> ${e(s.label)}</label>`).join("")}</fieldset>`;
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
  language: Language = "en",
): string {
  const t = translator(language);
  const T = (key: MessageKey) => e(t(key));
  return `<section><div class="page-heading"><div><h1>${T("nav.users")}</h1></div><div class="actions"><button type="button" class="secondary" data-open-dialog="import-users-dialog">${T("users.importWithings")}</button><button type="button" data-open-dialog="add-user-dialog">${T("users.add")}</button></div></div>
    ${
      preview
        ? `<dialog id="import-preview-dialog" data-auto-open><button class="dialog-close" type="button" data-close-dialog>×</button><h2>${e(t("users.importFrom", { scale: String(preview.scale.label ?? "") }))}</h2><p>${preview.settingsStatus === "configured" || scaleModel(preview.scale.model)?.classicGates ? T("users.settingsReady") : T("users.settingsIncomplete")} ${T("users.retained")}</p>
      <form action="/users/import-withings/confirm" method="post">${hidden(csrf)}<input type="hidden" name="scale_id" value="${e(preview.scale.id)}"><input type="hidden" name="capture_digest" value="${e(preview.digest)}">
      ${preview.users.length ? preview.users.map((u) => `<label><input type="checkbox" name="user_ids" value="${e(u.id)}" checked> ${e(u.fn || u.sn)} · ${e(u.sn)} · ID ${e(u.id)}</label>`).join("") : `<p>${T("users.allPresent")}</p>`}
      <div class="dialog-actions"><button>${T("users.importSelected")}</button><button type="button" class="secondary" data-close-dialog>${T("common.later")}</button></div></form></dialog>`
        : ""
    }
    ${
      users.length
        ? `<div class="wide"><table><thead><tr><th>${T("users.name")}</th><th>${T("users.shortName")}</th><th>${T("users.height")}</th><th>${T("users.ageDob")}</th><th>${T("users.sex")}</th><th>${T("nav.scales")}</th><th>${T("users.status")}</th><th></th></tr></thead><tbody>
    ${users
      .map(
        (
          u,
        ) => `<tr><td>${e(u.name)}</td><td>${e(u.short_name)}</td><td>${Math.round(n(u.height_cm))} cm</td><td>${e(u.birth_date || u.age_years)}</td><td>${u.sex === 0 ? T("users.male") : T("users.female")}</td>
      <td>${scales
        .filter((s) => memberships.get(u.id)?.has(s.id))
        .map((s) => e(s.label))
        .join(
          ", ",
        )}</td><td>${u.active ? T("users.active") : T("users.retired")}</td><td><button type="button" class="secondary" data-open-dialog="edit-user-${e(u.id)}">${T("common.edit")}</button></td></tr>`,
      )
      .join("")}</tbody></table></div>`
        : `<p class="empty">${T("dashboard.noUsers")}</p>`
    }</section>
    <dialog id="import-users-dialog"${importScaleId ? " data-auto-open" : ""}><button type="button" class="dialog-close" data-close-dialog>×</button><h2>${T("users.importWithings")}</h2>
      <p>${T("users.importIntro")}</p>
      ${fetchMode ? `<form action="/users/fetch-withings" method="post">${hidden(csrf)}<label>${T("dashboard.scale")}<select name="scale_id" required><option value="">${T("users.chooseScale")}</option>${scales.map((s) => option(s.id, s.label, importScaleId ?? "")).join("")}</select></label><button>${T("users.fetch")}</button></form>` : `<p>${T("users.importUnavailable")}</p>`}</dialog>
    <dialog id="add-user-dialog"><button type="button" class="dialog-close" data-close-dialog>×</button><h2>${T("users.add")}</h2><form action="/users" method="post">${hidden(csrf)}${userFields(null, scales, new Set(), t)}<button>${T("users.save")}</button></form></dialog>
    ${users
      .map(
        (
          u,
        ) => `<dialog id="edit-user-${e(u.id)}"><button type="button" class="dialog-close" data-close-dialog>×</button><h2>${e(t("users.edit", { name: String(u.name ?? "") }))}</h2>
      <form action="/users/${e(u.id)}" method="post">${hidden(csrf)}${userFields(u, scales, memberships.get(u.id) ?? new Set(), t)}<div class="dialog-actions"><button>${T("users.save")}</button></div></form>
      <div class="dialog-actions"><form action="/users/${e(u.id)}" method="post">${hidden(csrf)}<input type="hidden" name="purpose" value="retire"><button class="secondary">${T("users.retire")}</button></form>
      <form action="/users/${e(u.id)}/delete" method="post" data-confirm="${T("users.confirmDelete")}">${hidden(csrf)}<button class="danger">${T("users.delete")}</button></form></div></dialog>`,
      )
      .join("")}`;
}
