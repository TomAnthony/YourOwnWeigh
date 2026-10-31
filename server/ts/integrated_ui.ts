/** Household and firmware views; all Bluetooth operations belong to the bridge. */
import { escapeHtml as e, hidden, timeLabel } from "./ui.ts";
import { WEB_APP_VERSION } from "./version.ts";
type Row = Record<string, any>;

export function timeZoneSelect(name: string, value = "", id = ""): string {
  return `<select name="${e(name)}"${id ? ` id="${e(id)}"` : ""} data-timezone-select data-selected-zone="${e(value)}"><option value="${e(value || "UTC")}">${e(value || "UTC")}</option></select>`;
}

export function firmwareWorkspace(csrf: string): string {
  return `<div id="firmware-workspace" data-csrf="${e(csrf)}"><section class="bridge-heading"><h1>Firmware Bridge</h1><div id="bridge-connection" class="bridge-status is-offline"><span class="status-dot" aria-hidden="true"></span><span id="bridge-status-text" role="status">Python Bridge Not Connected</span><button type="button" id="revoke-bridge" class="text-button" title="Disconnect from this server. An active firmware transfer continues locally." hidden>Disconnect Bridge</button></div></section>
    <section id="bridge-offline"><h2>Connect The Python Bridge</h2>
      <p>Run the bridge on your Mac or Linux computer and leave it running while setting up a scale.</p>
      <ol><li>Install: <code>python3.11 -m venv .venv &amp;&amp; .venv/bin/pip install ./bridge</code></li>
      <li>Run <code>.venv/bin/yow-bridge</code> in Terminal.</li><li>Generate an invitation and paste it into Terminal.</li></ol>
      <div class="action-row"><button id="new-invitation" type="button">Generate Connection Invitation</button><button id="copy-invitation" class="secondary" type="button" hidden>Copy Invitation</button></div>
      <label id="invitation-label" hidden>Connection Invitation<textarea id="bridge-invitation" readonly rows="3" spellcheck="false"></textarea></label>
      <p class="hint">Invitations last ten minutes. Allow Bluetooth access for Terminal when macOS asks.</p></section>
    <div id="bridge-online" hidden>
      <section id="connect-panel"><div class="section-heading"><h2>Connect</h2><span class="badge" id="connection-state">Disconnected</span></div>
        <p class="hint">Put your scale into setup mode with its hardware button.</p>
        <div class="action-row"><button id="scan-ble" type="button" title="Find Body WBS06 and Body Smart WBS13 scales using Bluetooth Low Energy.">Scan BLE</button><button id="scan-classic" type="button" title="Find WS-30 scales using Bluetooth Classic.">Scan Classic</button><span id="scan-status" role="status" aria-live="polite"></span></div>
        <div id="candidates" class="wide"></div>
        <dl id="device-identity" class="identity-grid"></dl>
        <div id="unsupported-firmware" class="unsupported-firmware form-block" hidden>
          <h3>Help Identify This Scale</h3><p class="hint">This scale answered the identity probe, but its model is not yet supported for setup or updates. You can ask Withings what firmware it offers without installing anything. The device MAC and secret are used for this request and are excluded from the details you copy.</p>
          <div class="field-list"><label>Model Code From Scale Label<input id="offer-model-code" placeholder="WBS08" maxlength="6" autocapitalize="characters" spellcheck="false" required></label><label>Firmware Version To Report<input id="offer-reported-version" type="number" min="0" max="65535" required></label><label>Manufacturer ID (If Known)<input id="offer-manufacturer-id" type="number" min="0" max="2147483647" value="0"></label></div>
          <p class="hint">Reporting one version below the probed version can reveal the current stock image. A missing offer does not prove that no firmware exists.</p>
          <button id="check-firmware-offer" type="button">Check Withings Firmware Offer</button>
          <div id="firmware-offer-result" class="firmware-offer-result" hidden><dl class="identity-grid"><dt>Firmware URL</dt><dd id="offer-url"></dd><dt>SHA-1</dt><dd><code id="offer-hash"></code></dd></dl><p class="hint">Metadata reported by Withings. The image has not been downloaded or verified.</p><button id="copy-firmware-offer" type="button" class="secondary">Copy GitHub Issue Details</button></div>
        </div>
        <div class="action-row connection-actions"><button id="complete-setup" type="button" disabled title="End setup without changing Wi-Fi, hostname, or other settings.">Complete Setup</button><button id="disconnect" type="button" class="text-button" disabled>Disconnect Scale</button><button id="probe" type="button" class="text-button" hidden>Retry Connection Check</button><button id="reveal-secret" type="button" class="text-button" hidden>Reveal Secret</button><button id="import-device" type="button" class="text-button" hidden>Import Device</button><button id="export-device" type="button" class="text-button" hidden>Download Device Export</button></div>
        <code id="device-secret" hidden></code>
      </section>
      <div class="firmware-grid">
        <section id="firmware-panel"><h2>Firmware</h2>
          <div class="form-block"><label>Target Model<select id="scale-model"><option value="WBS06">Body (WBS06)</option><option value="WBS03">WS-30 (WBS03)</option><option value="WBS13">Body Smart (WBS13) · Experimental</option></select></label>
          <p class="hint">Download stock firmware and generate YourOwnWeigh firmware. Files stay on the computer running the bridge.</p>
          <div class="action-row"><button id="generate-firmware" type="button">Generate Firmware For WBS06</button><label class="text-button file-link">Select Manually<input id="manual-firmware" type="file" accept=".bin" hidden></label></div></div>
          <div id="firmware-info" class="firmware-artifact" hidden></div>
          <div class="action-row"><button id="install-firmware" type="button" disabled>Send Update To Device</button><button id="download-firmware" type="button" class="text-button" hidden>Download Firmware</button></div>
          <div id="operation-status" class="inline-status" hidden aria-live="polite"><p id="operation-message"></p><progress id="operation-progress" hidden max="1" value="0" aria-label="Firmware Progress"></progress></div>
        </section>
        <section id="configure-panel"><div class="section-heading"><h2>Configure</h2><button id="read-configuration" type="button" class="text-button" disabled>Read From Scale</button></div>
          <form id="server-form" class="form-block"><h3>Server</h3><label>Server Hostname<input id="server-host" autocomplete="off" placeholder="scales.example.com" required></label><button id="use-this-host" type="button" class="text-button">Use This Server’s Hostname</button>
          <label>Transport<select id="server-transport"><option value="https">HTTPS</option><option value="http">HTTP</option></select></label><p id="host-limits" class="hint"></p><button id="set-server" disabled>Save Server On Scale</button></form>
          <form id="wifi-form" class="form-block"><h3>Wi-Fi</h3><label>Wi-Fi Name (SSID)<input id="wifi-ssid" maxlength="32" autocomplete="off" required></label><label>Wi-Fi Password<input id="wifi-password" type="password" autocomplete="new-password" minlength="8" required></label><p id="wifi-password-hint" class="hint">Enter the password to save or reconnect this network.</p><button id="connect-wifi" disabled>Connect Wi-Fi</button><p id="wifi-status" class="hint" role="status"></p></form>
          <div class="form-block"><h3>Time Zone</h3><label>Scale Time Zone${timeZoneSelect("time_zone", "", "scale-timezone")}</label><button id="set-time" class="secondary" type="button" disabled>Save Time Zone</button><p class="hint">Time-zone changes are also sent on future Wi-Fi syncs for an imported scale.</p></div>
        </section>
      </div>
    </div>
    <div id="toast-region" class="toast-region" aria-live="polite" aria-relevant="additions" aria-label="Notifications"></div>
    <dialog id="flash-dialog"><button class="dialog-close" data-close-dialog type="button">×</button><h2>Install Firmware?</h2><p>This replaces an external firmware slot. Keep the scale powered and the Python bridge running until transfer finishes. Keep your original firmware backup and recovery instructions.</p><p id="flash-summary"></p><label>Type FLASH<input id="flash-confirmation" autocomplete="off"></label><div class="dialog-actions"><button id="confirm-flash" type="button" disabled>Confirm Update</button><button type="button" data-close-dialog class="secondary">Cancel</button></div></dialog>
    <dialog id="enroll-dialog"><button class="dialog-close" type="button" data-close-dialog>×</button><h2>Import Device To Server?</h2><p id="enroll-description">Save this scale and check Withings for existing users and settings. You choose which new users to import.</p><label>Scale Name<input id="device-label" maxlength="80"></label><div class="dialog-actions"><button id="confirm-enroll" type="button">Import Device</button><button type="button" data-close-dialog class="secondary">Later</button></div></dialog>
    <dialog id="roster-dialog"><button class="dialog-close" type="button" data-close-dialog>×</button><h2>Import Users</h2><p id="roster-message"></p><div id="roster-users"></div><div class="dialog-actions"><button id="confirm-roster" type="button">Import Selected Users</button><button type="button" data-close-dialog class="secondary">Later</button></div></dialog>
  </div><script src="/firmware.js?v=${WEB_APP_VERSION}" defer></script>`;
}

function editDevice(s: Row, csrf: string, users: Row[]): string {
  const advanced = [
    ["goff", "UTC Offset (Seconds)"],
    ["dst", "Next DST Change (Unix Time)"],
    ["ngoff", "Next UTC Offset (Seconds)"],
    ["feature_mask", "Feature Mask"],
    ["beta_ws", "Beta Services (0 Or 1)"],
    ["temp_code", "Temperature Unit Code"],
    ["weight_code", "Weight Unit Code"],
  ];
  return `<dialog id="edit-device-${e(s.id)}"><button class="dialog-close" data-close-dialog type="button">×</button><h2>Edit Settings</h2>
    <form action="/scales/${e(s.id)}" method="post">${hidden(csrf)}<input type="hidden" name="purpose" value="device_config">
    <label>Name<input name="label" value="${e(s.label)}" maxlength="80" required></label><label>Time Zone${timeZoneSelect("time_zone", s.time_zone || "")}</label>
    ${s.model === "WBS13" ? `<fieldset><legend>Users On This Scale</legend><p>Choose the local users to send on each sync. This replaces the scale’s current roster; Withings import is unavailable for this model.</p>${users.map((u) => `<label><input type="checkbox" name="user_ids" value="${e(u.id)}"${s.userIds?.includes(u.id) ? " checked" : ""}> ${e(u.name)}</label>`).join("") || '<p><a href="/users">Add A User</a> first.</p>'}</fieldset>` : ""}
    <details class="advanced-settings"><summary>Advanced</summary><dl class="identity-grid"><dt>Last Sync</dt><dd>${s.last_session_at ? timeLabel(s.last_session_at) : "Not Yet Seen"}</dd></dl><p class="hint">Internal protocol settings. The selected time zone supplies clock offsets automatically.</p><div class="field-list">${["WBS03", "WBS13"].includes(s.model) ? "" : advanced.map(([key, label]) => `<label>${label}<input type="number" name="${key}" value="${e(s[key] ?? 0)}"></label>`).join("")}</div>${s.model === "WBS03" ? '<p class="hint">WS-30 retains its internal settings and on-scale users.</p>' : ""}</details>
    <div class="dialog-actions"><button>Save Settings</button><button class="secondary" type="button" data-close-dialog>Cancel</button></div></form>${s.model === "WBS13" ? "" : `<form action="/users/fetch-withings" method="post" class="modal-secondary-action">${hidden(csrf)}<input type="hidden" name="scale_id" value="${e(s.id)}"><button class="text-button">${s.model !== "WBS03" && !s.settings_ready ? "Finish Device Import" : "Import Users From Withings"}</button></form>`}</dialog>`;
}
function firmwareRow(s: Row): string {
  const known = s.firmware_version != null && s.firmware_confirmed_at != null;
  const hint = known
    ? `Last confirmed ${new Date(s.firmware_confirmed_at * 1000).toISOString().replace("T", " ").replace(".000Z", " UTC")} via ${s.firmware_source === "wifi" ? "Wi-Fi sync" : "Bluetooth"}. This is the last observed running version.`
    : "No firmware version observed yet. Connect and probe this scale, import its device export, or let it sync over Wi-Fi.";
  return `<tr><th>Firmware <span class="info-tip" tabindex="0" aria-label="Firmware Confirmation" aria-describedby="firmware-time-${e(s.id)}"><span aria-hidden="true">ⓘ</span><span role="tooltip" id="firmware-time-${e(s.id)}">${e(hint)}</span></span></th><td>${known ? `v${e(s.firmware_version)}` : "Not Yet Confirmed"}</td></tr>`;
}
export function scalesWorkspace(
  scales: Row[],
  csrf: string,
  users: Row[] = [],
): string {
  return `<section class="page-heading"><h1>Scales</h1></section>
    <div class="scale-cards">${
      scales.length
        ? scales
            .map(
              (
                s,
              ) => `<section class="scale-card" id="scale-${e(s.id)}"><div class="section-heading"><h2>${e(s.label)}</h2><span class="badge${s.model !== "WBS03" && !s.settings_ready ? " warn" : ""}">${s.model === "WBS03" || s.settings_ready ? "Ready" : s.model === "WBS13" ? "Choose Users" : "Import Incomplete"}</span></div>
      <table class="scale-details"><tbody><tr><th>Model</th><td>${s.model === "WBS03" ? "Wireless Scale (WBS03 / WS-30)" : s.model === "WBS13" ? "Body Smart (WBS13)" : "Body Scale (WBS06)"}</td></tr><tr><th>MAC</th><td><code>${e(
        String(s.mac)
          .replace(/(..)(?=.)/g, "$1:")
          .toUpperCase(),
      )}</code></td></tr>${firmwareRow(s)}<tr><th>Secret</th><td><button class="secret-reveal" type="button" data-reveal-secret="scale-secret-${e(s.id)}" aria-expanded="false">•••••••••••••••• <span class="hint">(Click To Reveal)</span></button><code id="scale-secret-${e(s.id)}" hidden>${e(s.secret)}</code></td></tr></tbody></table>
      <button type="button" class="text-button" data-open-dialog="edit-device-${e(s.id)}">Edit Settings</button></section>`,
            )
            .join("")
        : '<section><p class="empty">No scales yet.</p><a class="button" href="/firmware">Connect A Scale</a></section>'
    }</div>
    ${scales.map((s) => editDevice(s, csrf, users)).join("")}
    <div class="page-footer"><button class="text-button" type="button" data-open-dialog="device-file-dialog">Import Device File</button></div>
    <dialog id="device-file-dialog"><button class="dialog-close" data-close-dialog type="button">×</button><h2>Import Device File</h2><form action="/scales/import-ble" method="post" enctype="multipart/form-data">${hidden(csrf)}<label>Name (Optional)<input name="label" maxlength="80"></label><label>Device Export<input type="file" name="record" accept=".json" required></label><label>Time Zone${timeZoneSelect("time_zone")}</label><button>Import Device</button></form></dialog>`;
}
export function syncPage(origin: string, users: Row[]): string {
  return `<section class="page-heading"><h1>Sync</h1></section>
    <div class="firmware-grid"><section><h2>Apple Health</h2><p>Download the static signed Shortcut, then set its first three Text actions. You can install and configure it on your Mac; iCloud syncs it to Shortcuts on your iPhone. Run it on the iPhone to grant Health access.</p>
    <a class="button" href="/YourOwnWeigh-Sync.shortcut" download="YourOwnWeigh Sync.shortcut">Download YourOwnWeigh Sync</a><dl><dt>Server URL</dt><dd><code>${e(origin)}</code></dd><dt>User ID Or Three-Letter Name</dt><dd>${users.map((u) => `${e(u.name)}: <code>${e(u.id)}</code> / <code>${e(u.short_name)}</code>`).join("<br>") || "Add a user first."}</dd><dt>Password</dt><dd>Your Sync API password (the admin password unless you set a separate one).</dd></dl>
    <p class="hint">For a daily sync, create a Personal Automation in iPhone Shortcuts: Time Of Day → 09:00 → Daily → Run Immediately → Run Shortcut → YourOwnWeigh Sync. Run the Shortcut manually any time too.</p></section>
    <section><h2>Read Over HTTP</h2><p>Use a numeric user ID or an unambiguous three-letter display name. Requests return JSON and do not mark readings as imported into Apple Health.</p><pre>curl --user reader \\\n  '${e(origin)}/api/users/USER/readings?since=2026-01-01'</pre><p class="hint">curl prompts for the password. Use HTTPS for remote servers. The household credential can read every user; the selected ID controls this request, not access rights.</p><p><code>/readings</code> returns all measurement groups, named metrics and raw values. Follow <code>next_cursor</code> using the <code>cursor</code> parameter to paginate. <code>/weights</code> remains available for weight-only clients.</p><p>The Apple Shortcut uses the separate <code>health-sync/next</code> and <code>health-sync/ack</code> endpoints so it acknowledges a reading only after writing it to Health.</p></section></div>`;
}
export function settingsWorkspace(
  csrf: string,
  unit: string,
  separate: boolean,
): string {
  return `<section class="page-heading"><h1>Settings</h1></section><div class="firmware-grid"><section><h2>Display</h2><form action="/preferences" method="post">${hidden(csrf)}<label>Weight Unit<select name="weight_unit">${[
    ["kg", "Kilograms"],
    ["lb", "Pounds"],
    ["st", "Stones And Pounds"],
  ]
    .map(
      ([v, l]) =>
        `<option value="${v}"${v === unit ? " selected" : ""}>${l}</option>`,
    )
    .join(
      "",
    )}</select></label><button>Save Display Settings</button></form></section>
    <section class="backup-panel"><h2>Backup And Restore</h2><p>Back up your household or restore a saved export.</p><div class="action-row"><a class="button secondary" href="/api/backup/export">Export Database</a><button type="button" class="secondary" data-open-dialog="backup-import-dialog">Import Database</button></div><p class="hint">Exports include device secrets and password hashes. Keep them private.</p></section></div>
    <dialog id="backup-import-dialog"><button class="dialog-close" data-close-dialog type="button" aria-label="Close">×</button><h2>Import Database</h2><p>Choose a saved database export. You can review it before adding missing data or replacing the household.</p><form id="backup-import" action="/api/backup/import" method="post" enctype="multipart/form-data">${hidden(csrf)}<label>Backup File<input type="file" name="backup" accept=".json" required></label><p class="hint">Your current passwords stay unless you explicitly choose to restore access settings.</p><div class="dialog-actions"><button>Review Import</button><button type="button" class="secondary" data-close-dialog>Cancel</button></div></form></dialog>
    <div class="firmware-grid"><section><h2>Admin Password</h2><p>${separate ? "The Sync API uses a separate password." : "The Sync API uses this password too. Update your Shortcut after changing it."}</p><form action="/settings" method="post">${hidden(csrf)}<input type="hidden" name="purpose" value="admin_password"><label>Current Admin Password<input name="current" type="password" required></label><label>New Password<input name="new" type="password" minlength="8" required></label><label>Confirm Password<input name="confirm" type="password" minlength="8" required></label><button>Change Admin Password</button></form></section>
    <section><h2>Sync API Password</h2><form action="/settings" method="post">${hidden(csrf)}<input type="hidden" name="purpose" value="sync_password"><label>Current Admin Password<input name="current_admin" type="password" required></label><label><input type="checkbox" name="separate" value="1" data-toggle="sync-password-fields"${separate ? " checked" : ""}> Set Alternative Password For Sync API</label><div id="sync-password-fields"${separate ? "" : " hidden"}><label>New Sync Password<input name="new" type="password" minlength="8"></label><label>Confirm Sync Password<input name="confirm" type="password" minlength="8"></label></div><button>Save Sync Password Settings</button></form></section></div>`;
}
