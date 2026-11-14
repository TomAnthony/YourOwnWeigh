/** Household and firmware views; all Bluetooth operations belong to the bridge. */
import {
  LANGUAGE_NAMES,
  LANGUAGES,
  translator,
  type Language,
  type LanguagePreference,
  type MessageKey,
} from "./i18n.ts";
import { SCALE_MODELS, scaleModel } from "./models.ts";
import {
  batteryAction,
  batteryOf,
  escapeHtml as e,
  hidden,
  LOW_BATTERY,
  timeLabel,
} from "./ui.ts";
import { WEB_APP_VERSION } from "./version.ts";
type Row = Record<string, any>;

export function timeZoneSelect(name: string, value = "", id = ""): string {
  return `<select name="${e(name)}"${id ? ` id="${e(id)}"` : ""} data-timezone-select data-selected-zone="${e(value)}"><option value="${e(value || "UTC")}">${e(value || "UTC")}</option></select>`;
}

export function firmwareWorkspace(
  csrf: string,
  language: Language = "en",
): string {
  const t = translator(language);
  const T = (key: MessageKey) => e(t(key));
  return `<div id="firmware-workspace" data-csrf="${e(csrf)}" data-local-roster-models="${Object.keys(SCALE_MODELS).filter((model) => SCALE_MODELS[model].localRoster).join(",")}"><section class="bridge-heading"><h1>${T("nav.firmware")}</h1><div id="bridge-connection" class="bridge-status is-offline"><span class="status-dot" aria-hidden="true"></span><span id="bridge-status-text" role="status">${T("bridge.notConnected")}</span><button type="button" id="revoke-bridge" class="text-button" title="${T("bridge.disconnectHint")}" hidden>${T("bridge.disconnect")}</button></div></section>
    <section id="bridge-offline"><h2>${T("bridge.connectTitle")}</h2>
      <p>${T("bridge.connectIntro")}</p>
      <ol><li>${T("bridge.stepInstall")}<code>python3.11 -m venv .venv &amp;&amp; .venv/bin/pip install ./bridge</code></li>
      <li>${T("bridge.stepRunBefore")}<code>.venv/bin/yow-bridge</code>${T("bridge.stepRunAfter")}</li><li>${T("bridge.stepInvite")}</li></ol>
      <div class="action-row"><button id="new-invitation" type="button">${T("bridge.newInvitation")}</button><button id="copy-invitation" class="secondary" type="button" hidden>${T("bridge.copyInvitation")}</button></div>
      <label id="invitation-label" hidden>${T("bridge.invitation")}<textarea id="bridge-invitation" readonly rows="3" spellcheck="false"></textarea></label>
      <p class="hint">${T("bridge.invitationHint")}</p></section>
    <div id="bridge-online" hidden>
      <section id="connect-panel"><div class="section-heading"><h2>${T("bridge.connect")}</h2><span class="badge" id="connection-state">${T("bridge.disconnected")}</span></div>
        <p class="hint">${T("bridge.setupMode")}</p>
        <div class="action-row"><button id="scan-ble" type="button" title="${T("bridge.scanBleHint")}">${T("bridge.scanBle")}</button><button id="scan-classic" type="button" title="${T("bridge.scanClassicHint")}">${T("bridge.scanClassic")}</button><span id="scan-status" role="status" aria-live="polite"></span></div>
        <div id="candidates" class="wide"></div>
        <dl id="device-identity" class="identity-grid"></dl>
        <p id="connection-warning" class="notice" role="alert" hidden></p>
        <div id="unsupported-firmware" class="unsupported-firmware form-block" hidden>
          <h3>${T("bridge.identifyTitle")}</h3><p class="hint">${T("bridge.identifyIntro")}</p>
          <div class="field-list"><label>${T("bridge.modelCode")}<input id="offer-model-code" placeholder="WBS08" maxlength="6" autocapitalize="characters" spellcheck="false" required></label><label>${T("bridge.reportVersion")}<input id="offer-reported-version" type="number" min="0" max="65535" required></label><label>${T("bridge.manufacturerId")}<input id="offer-manufacturer-id" type="number" min="0" max="2147483647" value="0"></label></div>
          <p class="hint">${T("bridge.reportHint")}</p>
          <button id="check-firmware-offer" type="button">${T("bridge.checkOffer")}</button>
          <div id="firmware-offer-result" class="firmware-offer-result" hidden><dl class="identity-grid"><dt>${T("bridge.offerUrl")}</dt><dd id="offer-url"></dd><dt>SHA-1</dt><dd><code id="offer-hash"></code></dd></dl><p class="hint">${T("bridge.offerHint")}</p><button id="copy-firmware-offer" type="button" class="secondary">${T("bridge.copyIssue")}</button></div>
        </div>
        <div class="action-row connection-actions"><button id="complete-setup" type="button" disabled title="${T("bridge.completeHint")}">${T("bridge.complete")}</button><button id="disconnect" type="button" class="text-button" disabled>${T("bridge.disconnectScale")}</button><button id="probe" type="button" class="text-button" hidden>${T("bridge.probe")}</button><button id="reveal-secret" type="button" class="text-button" hidden>${T("bridge.revealSecret")}</button><button id="import-device" type="button" class="text-button" hidden>${T("bridge.importDevice")}</button><button id="export-device" type="button" class="text-button" hidden>${T("bridge.exportDevice")}</button></div>
        <code id="device-secret" hidden></code>
      </section>
      <div class="firmware-grid">
        <section id="firmware-panel"><h2>${T("bridge.firmware")}</h2>
          <div class="form-block"><label>${T("bridge.targetModel")}<select id="scale-model">${Object.entries(SCALE_MODELS).map(([v, m]) => `<option value="${v}">${m.label}</option>`).join("")}</select></label>
          <p class="hint">${T("bridge.firmwareIntro")}</p>
          <div class="action-row"><button id="generate-firmware" type="button">${T("bridge.generateWbs06")}</button><label class="text-button file-link">${T("bridge.selectManually")}<input id="manual-firmware" type="file" accept=".bin" hidden></label></div></div>
          <div id="firmware-info" class="firmware-artifact" hidden></div>
          <p id="firmware-warning" class="notice" hidden></p>
          <div class="action-row"><button id="install-firmware" type="button" disabled>${T("bridge.install")}</button><button id="download-firmware" type="button" class="text-button" hidden>${T("bridge.downloadFirmware")}</button></div>
          <div id="operation-status" class="inline-status" hidden aria-live="polite"><p id="operation-message"></p><progress id="operation-progress" hidden max="1" value="0" aria-label="${T("bridge.progress")}"></progress></div>
        </section>
        <section id="configure-panel"><div class="section-heading"><h2>${T("bridge.configure")}</h2><button id="read-configuration" type="button" class="text-button" disabled>${T("bridge.readConfig")}</button></div>
          <form id="server-form" class="form-block"><h3>${T("bridge.server")}</h3><label>${T("bridge.serverHost")}<input id="server-host" autocomplete="off" placeholder="scales.example.com" required></label><button id="use-this-host" type="button" class="text-button">${T("bridge.useThisHost")}</button>
          <label>${T("bridge.transport")}<select id="server-transport"><option value="https">HTTPS</option><option value="http">HTTP</option></select></label><p id="host-limits" class="hint"></p><button id="set-server" disabled>${T("bridge.setServer")}</button></form>
          <form id="wifi-form" class="form-block"><h3>${T("bridge.wifi")}</h3><label>${T("bridge.wifiSsid")}<input id="wifi-ssid" maxlength="32" autocomplete="off" required></label><label>${T("bridge.wifiPassword")}<input id="wifi-password" type="password" autocomplete="new-password" minlength="8" required></label><p id="wifi-password-hint" class="hint">${T("bridge.wifiPasswordHint")}</p><button id="connect-wifi" disabled>${T("bridge.connectWifi")}</button><p id="wifi-status" class="hint" role="status"></p></form>
          <div class="form-block"><h3>${T("common.timeZone")}</h3><label>${T("bridge.scaleTimeZone")}${timeZoneSelect("time_zone", "", "scale-timezone")}</label><button id="set-time" class="secondary" type="button" disabled>${T("bridge.setTime")}</button><p class="hint">${T("bridge.timeHint")}</p></div>
        </section>
      </div>
    </div>
    <div id="toast-region" class="toast-region" aria-live="polite" aria-relevant="additions" aria-label="${T("common.notifications")}"></div>
    <dialog id="flash-dialog"><button class="dialog-close" data-close-dialog type="button">×</button><h2 id="flash-title">${T("bridge.flashTitle")}</h2><p id="flash-warning" class="notice" hidden></p><p>${T("bridge.flashIntro")}</p><p id="flash-summary" class="firmware-artifact"></p><label><span id="flash-prompt">${T("bridge.flashPrompt")}</span><input id="flash-confirmation" autocomplete="off" spellcheck="false" aria-describedby="flash-warning flash-summary"></label><div class="dialog-actions"><button id="confirm-flash" type="button" disabled>${T("bridge.confirmFlash")}</button><button type="button" data-close-dialog class="secondary">${T("common.cancel")}</button></div></dialog>
    <dialog id="enroll-dialog"><button class="dialog-close" type="button" data-close-dialog>×</button><h2>${T("bridge.enrollTitle")}</h2><p id="enroll-description">${T("bridge.enrollIntro")}</p><label>${T("bridge.deviceLabel")}<input id="device-label" maxlength="80"></label><div class="dialog-actions"><button id="confirm-enroll" type="button">${T("bridge.importDevice")}</button><button type="button" data-close-dialog class="secondary">${T("common.later")}</button></div></dialog>
    <dialog id="roster-dialog"><button class="dialog-close" type="button" data-close-dialog>×</button><h2>${T("bridge.rosterTitle")}</h2><p id="roster-message"></p><div id="roster-users"></div><div class="dialog-actions"><button id="confirm-roster" type="button">${T("users.importSelected")}</button><button type="button" data-close-dialog class="secondary">${T("common.later")}</button></div></dialog>
  </div><script src="/firmware.js?v=${WEB_APP_VERSION}" defer></script>`;
}

function editDevice(
  s: Row,
  csrf: string,
  users: Row[],
  language: Language,
): string {
  const t = translator(language);
  const T = (key: MessageKey) => e(t(key));
  const advanced: Array<[string, MessageKey]> = [
    ["goff", "scales.goff"],
    ["dst", "scales.dst"],
    ["ngoff", "scales.ngoff"],
    ["feature_mask", "scales.featureMask"],
    ["beta_ws", "scales.betaWs"],
    ["temp_code", "scales.tempCode"],
    ["weight_code", "scales.weightCode"],
  ];
  return `<dialog id="edit-device-${e(s.id)}"><button class="dialog-close" data-close-dialog type="button">×</button><h2>${T("scales.editSettings")}</h2>
    <form action="/scales/${e(s.id)}" method="post">${hidden(csrf)}<input type="hidden" name="purpose" value="device_config">
    <label>${T("users.name")}<input name="label" value="${e(s.label)}" maxlength="80" required></label><label>${T("common.timeZone")}${timeZoneSelect("time_zone", s.time_zone || "")}</label>
    ${scaleModel(s.model)?.localRoster ? `<fieldset><legend>${T("scales.usersOnScale")}</legend><p>${T("scales.usersOnScaleIntro")}</p>${users.map((u) => `<label><input type="checkbox" name="user_ids" value="${e(u.id)}"${s.userIds?.includes(u.id) ? " checked" : ""}> ${e(u.name)}</label>`).join("") || `<p>${t("scales.addUserFirst", { link: `<a href="/users">${T("scales.addUserLink")}</a>` })}</p>`}</fieldset>` : ""}
    <details class="advanced-settings"><summary>${T("scales.advanced")}</summary><dl class="identity-grid"><dt>${T("scales.lastSync")}</dt><dd>${s.last_session_at ? timeLabel(s.last_session_at, language) : T("scales.notYetSeen")}</dd></dl><p class="hint">${T("scales.advancedHint")}</p><div class="field-list">${scaleModel(s.model)?.transport === "classic" || scaleModel(s.model)?.localRoster ? "" : advanced.map(([key, label]) => `<label>${T(label)}<input type="number" name="${key}" value="${e(s[key] ?? 0)}"></label>`).join("")}</div>${scaleModel(s.model)?.classicGates ? `<p class="hint">${T("scales.classicRetains")}</p>` : ""}</details>
    <div class="dialog-actions"><button>${T("scales.saveSettings")}</button><button class="secondary" type="button" data-close-dialog>${T("common.cancel")}</button></div></form>${scaleModel(s.model)?.localRoster ? "" : `<form action="/users/fetch-withings" method="post" class="modal-secondary-action">${hidden(csrf)}<input type="hidden" name="scale_id" value="${e(s.id)}"><button class="text-button">${!scaleModel(s.model)?.classicGates && !s.settings_ready ? T("scales.finishImport") : T("scales.importUsers")}</button></form>`}</dialog>`;
}
function batteryRow(s: Row, language: Language): string {
  const t = translator(language);
  const T = (key: MessageKey) => e(t(key));
  const level = batteryOf(s);
  if (level === null)
    return `<tr><th>${T("battery.label")}</th><td>${T("battery.notReported")}</td></tr>`;
  const low = level <= LOW_BATTERY;
  return `<tr class="battery-row"><th>${T("battery.label")}</th><td>${level} %${low ? ` <span class="badge warn">${e(batteryAction(s.model, language))}</span>` : ""}<span class="hint">${e(t("battery.reported", { time: timeLabel(s.last_session_at, language) }))}</span></td></tr>`;
}
function firmwareRow(s: Row, language: Language): string {
  const t = translator(language);
  const known = s.firmware_version != null && s.firmware_confirmed_at != null;
  const hint = known
    ? t(s.firmware_source === "wifi" ? "scales.firmwareSeenWifi" : "scales.firmwareSeenBle", {
        time: new Date(s.firmware_confirmed_at * 1000)
          .toISOString()
          .replace("T", " ")
          .replace(".000Z", " UTC"),
      })
    : t("scales.firmwareUnknown");
  return `<tr><th>${e(t("bridge.firmware"))} <span class="info-tip" tabindex="0" aria-label="${e(t("scales.firmwareConfirmation"))}" aria-describedby="firmware-time-${e(s.id)}"><span aria-hidden="true">ⓘ</span><span role="tooltip" id="firmware-time-${e(s.id)}">${e(hint)}</span></span></th><td>${known ? `v${e(s.firmware_version)}` : e(t("scales.notYetConfirmed"))}</td></tr>`;
}
export function scalesWorkspace(
  scales: Row[],
  csrf: string,
  users: Row[] = [],
  language: Language = "en",
): string {
  const t = translator(language);
  const T = (key: MessageKey) => e(t(key));
  return `<section class="page-heading"><h1>${T("nav.scales")}</h1></section>
    <div class="scale-cards">${
      scales.length
        ? scales
            .map(
              (
                s,
              ) => `<section class="scale-card" id="scale-${e(s.id)}"><div class="section-heading"><h2>${e(s.label)}</h2><span class="badge${!scaleModel(s.model)?.classicGates && !s.settings_ready ? " warn" : ""}">${scaleModel(s.model)?.classicGates || s.settings_ready ? T("scales.ready") : scaleModel(s.model)?.localRoster ? T("scales.chooseUsers") : T("scales.importIncomplete")}</span></div>
      <table class="scale-details"><tbody><tr><th>${T("scales.model")}</th><td>${scaleModel(s.model)?.fullLabel ?? s.model}</td></tr><tr><th>MAC</th><td><code>${e(
        String(s.mac)
          .replace(/(..)(?=.)/g, "$1:")
          .toUpperCase(),
      )}</code></td></tr>${firmwareRow(s, language)}${batteryRow(s, language)}<tr><th>${T("scales.secret")}</th><td><button class="secret-reveal" type="button" data-reveal-secret="scale-secret-${e(s.id)}" aria-expanded="false">•••••••••••••••• <span class="hint">${T("scales.clickToReveal")}</span></button><code id="scale-secret-${e(s.id)}" hidden>${e(s.secret)}</code></td></tr></tbody></table>
      <button type="button" class="text-button" data-open-dialog="edit-device-${e(s.id)}">${T("scales.editSettings")}</button></section>`,
            )
            .join("")
        : `<section><p class="empty">${T("scales.none")}</p><a class="button" href="/firmware">${T("scales.connectFirst")}</a></section>`
    }</div>
    ${scales.map((s) => editDevice(s, csrf, users, language)).join("")}
    <div class="page-footer"><button class="text-button" type="button" data-open-dialog="device-file-dialog">${T("scales.importFile")}</button></div>
    <dialog id="device-file-dialog"><button class="dialog-close" data-close-dialog type="button">×</button><h2>${T("scales.importFile")}</h2><form action="/scales/import-ble" method="post" enctype="multipart/form-data">${hidden(csrf)}<label>${T("scales.nameOptional")}<input name="label" maxlength="80"></label><label>${T("scales.deviceExport")}<input type="file" name="record" accept=".json" required></label><label>${T("common.timeZone")}${timeZoneSelect("time_zone")}</label><button>${T("bridge.importDevice")}</button></form></dialog>`;
}
export function syncPage(
  origin: string,
  users: Row[],
  language: Language = "en",
): string {
  const t = translator(language);
  const T = (key: MessageKey) => e(t(key));
  // Catalog entries with markup are trusted source text, not user input.
  const H = (key: MessageKey) => t(key);
  return `<section class="page-heading"><h1>${T("nav.sync")}</h1></section>
    <div class="firmware-grid"><section><h2>${T("sync.appleHealth")}</h2><p>${T("sync.shortcutIntro")}</p>
    <a class="button" href="/YourOwnWeigh-Sync.shortcut" download="YourOwnWeigh Sync.shortcut">${T("sync.download")}</a><dl><dt>${T("sync.serverUrl")}</dt><dd><code>${e(origin)}</code></dd><dt>${T("sync.userId")}</dt><dd>${users.map((u) => `${e(u.name)}: <code>${e(u.id)}</code> / <code>${e(u.short_name)}</code>`).join("<br>") || T("sync.addUserFirst")}</dd><dt>${T("sync.password")}</dt><dd>${T("sync.passwordHint")}</dd></dl>
    <p class="hint">${T("sync.automationHint")}</p></section>
    <section><h2>${T("sync.http")}</h2><p>${T("sync.httpIntro")}</p><pre>curl --user reader \\\n  '${e(origin)}/api/users/USER/readings?since=2026-01-01'</pre><p class="hint">${T("sync.curlHint")}</p><p>${H("sync.readingsHint")}</p><p>${H("sync.healthSyncHint")}</p></section></div>`;
}
export function settingsWorkspace(
  csrf: string,
  unit: string,
  separate: boolean,
  languagePreference: LanguagePreference = "auto",
  language: Language = "en",
): string {
  const t = translator(language);
  const T = (key: MessageKey) => e(t(key));
  const options = (choices: Array<[string, string]>, selected: string) =>
    choices
      .map(
        ([v, l]) =>
          `<option value="${v}"${v === selected ? " selected" : ""}>${e(l)}</option>`,
      )
      .join("");
  return `<section class="page-heading"><h1>${T("nav.settings")}</h1></section><div class="firmware-grid"><section><h2>${e(t("settings.display"))}</h2><form action="/preferences" method="post">${hidden(csrf)}<label>${e(t("settings.weightUnit"))}<select name="weight_unit">${options(
    [
      ["kg", t("settings.unit.kg")],
      ["lb", t("settings.unit.lb")],
      ["st", t("settings.unit.st")],
    ],
    unit,
  )}</select></label><label>${e(t("settings.language"))}<select name="language">${options(
    [
      ["auto", t("settings.languageAuto")],
      ...LANGUAGES.map((l): [string, string] => [l, LANGUAGE_NAMES[l]]),
    ],
    languagePreference,
  )}</select></label><button>${e(t("settings.saveDisplay"))}</button></form></section>
    <section class="backup-panel"><h2>${T("settings.backup")}</h2><p>${T("settings.backupIntro")}</p><div class="action-row"><a class="button secondary" href="/api/backup/export">${T("settings.export")}</a><button type="button" class="secondary" data-open-dialog="backup-import-dialog">${T("settings.import")}</button></div><p class="hint">${T("settings.exportHint")}</p></section></div>
    <dialog id="backup-import-dialog"><button class="dialog-close" data-close-dialog type="button" aria-label="${T("common.close")}">×</button><h2>${T("settings.import")}</h2><p>${T("settings.importIntro")}</p><form id="backup-import" action="/api/backup/import" method="post" enctype="multipart/form-data">${hidden(csrf)}<label>${T("settings.backupFile")}<input type="file" name="backup" accept=".json" required></label><p class="hint">${T("settings.importHint")}</p><div class="dialog-actions"><button>${T("settings.reviewImport")}</button><button type="button" class="secondary" data-close-dialog>${T("common.cancel")}</button></div></form></dialog>
    <div class="firmware-grid"><section><h2>${T("auth.adminPassword")}</h2><p>${separate ? T("settings.syncSeparate") : T("settings.syncShared")}</p><form action="/settings" method="post">${hidden(csrf)}<input type="hidden" name="purpose" value="admin_password"><label>${T("settings.currentAdmin")}<input name="current" type="password" required></label><label>${T("settings.newPassword")}<input name="new" type="password" minlength="8" required></label><label>${T("settings.confirmPassword")}<input name="confirm" type="password" minlength="8" required></label><button>${T("settings.changeAdmin")}</button></form></section>
    <section><h2>${T("setup.syncPassword")}</h2><form action="/settings" method="post">${hidden(csrf)}<input type="hidden" name="purpose" value="sync_password"><label>${T("settings.currentAdmin")}<input name="current_admin" type="password" required></label><label><input type="checkbox" name="separate" value="1" data-toggle="sync-password-fields"${separate ? " checked" : ""}> ${T("sync.alternativePassword")}</label><div id="sync-password-fields"${separate ? "" : " hidden"}><label>${T("settings.newSync")}<input name="new" type="password" minlength="8"></label><label>${T("settings.confirmSync")}<input name="confirm" type="password" minlength="8"></label></div><button>${T("settings.saveSync")}</button></form></section></div>`;
}
