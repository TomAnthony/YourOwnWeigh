/* Browser controller for the versioned bridge contract. No Bluetooth or patching
 * logic lives here: commands are model-neutral and capabilities drive controls. */
(() => {
  "use strict";
  const root = document.getElementById("firmware-workspace");
  if (!root) return;
  const $ = (id) => document.getElementById(id);
  const csrf = root.dataset.csrf;
  let socket,
    clientId,
    snapshot = {},
    connected = false,
    busy = false,
    selectedArtifact = null,
    flashArtifact = null,
    migration = null,
    offerIdentityKey = null,
    offerReport = "";
  let knownDevices = [],
    prompted = new Set(),
    reconnectTimer,
    contactTimer,
    scanInProgress = false,
    actionSequence = 0;
  const pending = new Map();
  const notices = new Map();
  const buttons = [
    "scan-ble",
    "scan-classic",
    "probe",
    "disconnect",
    "complete-setup",
    "generate-firmware",
    "install-firmware",
    "read-configuration",
    "set-server",
    "connect-wifi",
    "set-time",
    "import-device",
    "export-device",
    "reveal-secret",
    "download-firmware",
    "check-firmware-offer",
  ];
  const label = (model) =>
    ({
      WBS03: "WS-30 (WBS03)",
      WBS13: "Body Smart (WBS13)",
      WBS04: "Body Cardio (WBS04)",
    })[model] || "WBS06";
  const uuid = () => crypto.randomUUID();
  const model = () => snapshot.device?.model || $("scale-model").value;
  const unknownFirmware = (artifact) =>
    !["known_release", "known_stock"].includes(artifact.classification);
  const flashPhrase = (artifact) =>
    unknownFirmware(artifact) ? "FLASH UNKNOWN" : "FLASH";
  const unknownFirmwareWarning =
    "This image does not match a known YOW release or stock firmware in this bridge. Its container checks passed, but its application has not been verified and could leave the scale unable to boot. Only continue if you trust this image and can recover the scale.";
  // Small, dismissible notices are independent of the persistent OTA progress.
  // Text is never interpreted as HTML; there are no third-party UI dependencies.
  const message = (text, error = false, key = uuid()) => {
    notices.get(key)?.();
    while (notices.size >= 3) notices.values().next().value();
    const toast = document.createElement("div");
    toast.className = `toast${error ? " toast-error" : ""}`;
    const icon = document.createElement("span");
    icon.className = "toast-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = error ? "!" : "✓";
    const content = document.createElement("span");
    content.textContent = text;
    const close = document.createElement("button");
    close.type = "button";
    close.className = "toast-close";
    close.setAttribute("aria-label", "Dismiss Notification");
    close.textContent = "×";
    let timer;
    const dismiss = () => {
      if (notices.get(key) !== dismiss) return;
      clearTimeout(timer);
      notices.delete(key);
      toast.classList.add("toast-leaving");
      setTimeout(() => toast.remove(), 250);
    };
    close.onclick = dismiss;
    toast.append(icon, content, close);
    $("toast-region").append(toast);
    notices.set(key, dismiss);
    timer = setTimeout(dismiss, 5000);
  };
  const progressMessage = (text, error = false) => {
    $("operation-status").hidden = false;
    $("operation-status").classList.toggle("error", error);
    $("operation-message").textContent = text;
    if (error) $("operation-progress").hidden = true;
  };
  function canConnect(candidate) {
    const seen = ["seen", "connected"].includes(candidate.presence);
    const scanning = scanInProgress && seen;
    return (
      connected &&
      snapshot.state !== "connected" &&
      (!busy || scanning) &&
      (snapshot.activeOperation?.state !== "running" ||
        (scanning && snapshot.activeOperation.name === "device.scan.start"))
    );
  }
  async function api(path, data) {
    const response = await fetch(
      path,
      data === undefined
        ? { headers: { Accept: "application/json" } }
        : {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRF-Token": csrf,
            },
            body: JSON.stringify(data),
          },
    );
    if (response.redirected)
      throw new Error("Your login expired. Reload this page and sign in.");
    let result;
    try {
      result = await response.json();
    } catch {
      throw new Error("Server returned an unexpected response");
    }
    if (!response.ok)
      throw new Error(result.error || `Request failed (${response.status})`);
    return result;
  }
  function updateControls() {
    const occupied = busy || snapshot.activeOperation?.state === "running";
    buttons.forEach((id) => ($(id).disabled = occupied || !connected));
    const device = snapshot.device,
      caps = device?.capabilities || {};
    const linked = snapshot.state === "connected";
    if (device?.model) $("scale-model").value = device.model;
    $("scale-model").disabled = occupied || linked;
    $("candidates").hidden = linked;
    for (const button of $("candidates").querySelectorAll(
      "button[data-device-id]",
    )) {
      const candidate = snapshot.candidates?.find(
        (c) => c.deviceId === button.dataset.deviceId,
      );
      button.disabled = !candidate || !canConnect(candidate);
    }
    $("scan-ble").disabled ||= linked;
    $("scan-classic").disabled ||= linked;
    const unsupported = device?.supported === false;
    $("manual-firmware").disabled = occupied || !connected || unsupported;
    $("generate-firmware").disabled ||= unsupported;
    $("probe").disabled ||= !linked;
    $("probe").hidden = !linked || !!device;
    $("disconnect").disabled ||= !linked;
    $("complete-setup").disabled ||=
      !device || unsupported || !caps.completeSetup;
    $("connect-wifi").disabled ||= !device || unsupported || !caps.wifiWrite;
    $("set-time").disabled ||= !device || unsupported || caps.setTime === false;
    $("read-configuration").disabled ||=
      !device || unsupported || (!caps.serverRead && !caps.wifiRead);
    $("set-server").disabled ||= !caps.serverWrite;
    $("install-firmware").disabled ||=
      !caps.ota || !selectedArtifact || selectedArtifact.model !== model();
    $("download-firmware").disabled ||= !selectedArtifact || unsupported;
    ["import-device", "export-device", "reveal-secret"].forEach((id) => {
      $(id).hidden =
        !device ||
        (unsupported && id !== "reveal-secret") ||
        (caps.enrollment === false && id !== "reveal-secret") ||
        (id === "reveal-secret" &&
          (device.secretAvailable === false || !$("device-secret").hidden));
      $(id).disabled ||=
        !device ||
        (unsupported && id !== "reveal-secret") ||
        (caps.enrollment === false && id !== "reveal-secret") ||
        (id === "reveal-secret" && device.secretAvailable === false);
    });
    $("check-firmware-offer").disabled ||=
      !unsupported ||
      device?.secretAvailable === false ||
      caps.vendorFirmwareOfferRead === false;
    $("check-firmware-offer").title =
      caps.vendorFirmwareOfferRead === false
        ? "This Model Requires A Separate Client-Certificate Firmware Lookup"
        : device?.secretAvailable === false
          ? "The Scale Did Not Provide The Secret Required For This Lookup"
          : "";
    $("connection-state").textContent = linked
      ? `Connected: ${unsupported ? "Unrecognised Scale" : label(device?.model || $("scale-model").value)}${device ? "" : " · Identification Required"}`
      : "Disconnected";
    $("generate-firmware").textContent =
      `Generate Firmware For ${label(model())}`;
    const limit = caps.hostnameMaxBytes || (model() === "WBS03" ? 59 : 48);
    $("server-host").maxLength = limit;
    $("host-limits").textContent =
      `Hostname Or IPv4 Address · Maximum ${limit} ASCII Bytes · No Scheme, Path Or Port`;
    const transports =
      caps.serverTransports ||
      (model() === "WBS03" ? ["http"] : ["http", "https"]);
    for (const option of $("server-transport").options)
      option.disabled = !transports.includes(option.value);
    if (!transports.includes($("server-transport").value))
      $("server-transport").value = transports[0];
    const loopback = ["127.0.0.1", "localhost", "[::1]"].includes(
      location.hostname,
    );
    $("use-this-host").disabled = loopback;
    $("use-this-host").textContent = loopback
      ? "Enter This Computer’s LAN Address"
      : `Use ${location.hostname}`;
  }
  function renderIdentity() {
    const target = $("device-identity");
    target.replaceChildren();
    const d = snapshot.device;
    if (!d) {
      $("device-secret").hidden = true;
      $("device-secret").textContent = "";
      $("unsupported-firmware").hidden = true;
      $("firmware-offer-result").hidden = true;
      offerIdentityKey = null;
      offerReport = "";
      return;
    }
    const unsupported = d.supported === false;
    $("unsupported-firmware").hidden = !unsupported;
    const identityKey = `${d.mac}:${d.firmwareVersion}:${d.name}`;
    if (unsupported && offerIdentityKey !== identityKey) {
      offerIdentityKey = identityKey;
      offerReport = "";
      $("firmware-offer-result").hidden = true;
      const code = String(d.name || "").match(/\b[A-Z]{2,4}\d{2}\b/i)?.[0];
      $("offer-model-code").value = code ? code.toUpperCase() : "";
      $("offer-reported-version").value = Math.max(
        0,
        Number(d.firmwareVersion) - 1,
      );
      $("offer-manufacturer-id").value = 0;
    }
    for (const [name, value] of [
      [
        "Model",
        unsupported
          ? `${d.name || "Unknown"} (Unrecognised ${d.model === "WBS03" ? "Classic" : "BLE"})`
          : label(d.model),
      ],
      ["MAC", d.mac],
      ["Firmware", d.firmwareVersion],
      ["Bootloader", d.bootloaderVersion],
      ...(d.secretAvailable === false
        ? [["Secret", "Not Provided By Scale"]]
        : []),
    ]) {
      const dt = document.createElement("dt"),
        dd = document.createElement("dd");
      dt.textContent = name;
      dd.textContent = value;
      target.append(dt, dd);
    }
  }
  async function identify() {
    message("Checking Device Identity…", false, "connection");
    snapshot.device = await command("device.probe");
    renderIdentity();
    await refreshKnown();
    const known = knownDevices.find((d) => d.mac === snapshot.device.mac);
    if (
      known &&
      snapshot.device.supported !== false &&
      snapshot.device.capabilities?.enrollment !== false
    ) {
      const d = snapshot.device;
      await api(`/api/scales/${known.id}/firmware-observation`, {
        mac: d.mac,
        model: d.model,
        firmwareVersion: d.firmwareVersion,
        observedAt: d.observedAt,
      });
    }
    if (known?.time_zone) $("scale-timezone").value = known.time_zone;
    if (snapshot.device.supported !== false) offerEnrollment();
    message(
      snapshot.device.supported === false
        ? "Identity Read · This Model Is Not Yet Supported"
        : "Connected And Ready",
      false,
      "connection",
    );
  }
  function renderCandidates(candidates) {
    const target = $("candidates");
    target.replaceChildren();
    if (!candidates?.length) return;
    const table = document.createElement("table");
    const header = table.createTHead().insertRow();
    for (const text of ["Device", "Address", "Presence", "Signal", ""]) {
      const th = document.createElement("th");
      th.textContent = text;
      header.append(th);
    }
    const body = table.createTBody();
    for (const candidate of candidates) {
      const row = body.insertRow();
      for (const value of [
        candidate.name,
        candidate.deviceId,
        candidate.presence === "paired_only"
          ? "Paired · Not Seen This Scan"
          : candidate.presence === "connected"
            ? "Connected To Computer"
            : candidate.presence === "seen"
              ? "Seen This Scan"
              : "Unknown",
        candidate.rssi == null ? "—" : `${candidate.rssi} dBm`,
      ]) {
        row.insertCell().textContent = value;
      }
      const button = document.createElement("button");
      button.type = "button";
      button.className = "text-button";
      button.textContent = "Connect";
      button.dataset.deviceId = candidate.deviceId;
      button.disabled = !canConnect(candidate);
      button.title = scanInProgress
        ? candidate.presence === "paired_only"
          ? "Available when seen nearby or when this scan finishes"
          : "Stop scanning and connect to this scale"
        : "Connect and identify this scale";
      button.addEventListener("click", () =>
        action(
          async () => {
            message("Connecting…", false, "connection");
            const result = await command(
              "device.connect",
              {},
              { deviceId: candidate.deviceId },
            );
            snapshot = {
              ...snapshot,
              ...result,
              device: null,
              state: "connected",
            };
            $("scale-model").value = candidate.modelCandidate;
            renderIdentity();
            updateControls();
            await identify();
          },
          { interruptScan: true },
        ),
      );
      row.insertCell().append(button);
    }
    target.append(table);
  }
  function scanStatus(state) {
    const status = $("scan-status");
    status.classList.toggle("scanning", state === "scanning");
    status.replaceChildren(
      document.createTextNode(
        state === "scanning"
          ? "Scanning"
          : state === "complete"
            ? "Scan Complete"
            : state === "stopped"
              ? "Scan Stopped"
              : "Scan Interrupted",
      ),
    );
    if (state === "scanning") {
      const dots = document.createElement("span");
      dots.className = "scan-dots";
      dots.setAttribute("aria-hidden", "true");
      for (let i = 0; i < 3; i++) {
        const dot = document.createElement("span");
        dot.textContent = ".";
        dots.append(dot);
      }
      status.append(dots);
    }
  }
  function command(name, parameters = {}, overrides = {}) {
    if (!clientId || !connected)
      return Promise.reject(new Error("Connect the local Python bridge first"));
    const id = uuid(),
      operationId = uuid();
    return new Promise((resolve, reject) => {
      // A firmware transfer may take minutes. UI timeout never cancels it.
      const timer = setTimeout(
        () => {
          pending.delete(id);
          reject(
            new Error(
              "No final response yet. Check the bridge terminal; an active firmware transfer continues locally.",
            ),
          );
        },
        name === "firmware.install" ? 30 * 60 * 1000 : 180000,
      );
      pending.set(id, { resolve, reject, timer, name, operationId });
      if (name === "firmware.install")
        renderOperation({
          operationId,
          name,
          state: "running",
          stage: "requesting update",
          bytesDone: 0,
          bytesTotal: selectedArtifact?.size,
        });
      api("/api/bridge/commands", {
        id,
        operationId,
        clientId,
        name,
        parameters,
        deviceId: snapshot.deviceId,
        connectionGeneration: snapshot.connectionGeneration,
        ...overrides,
      }).catch((error) => {
        clearTimeout(timer);
        pending.delete(id);
        reject(error);
      });
    });
  }
  function renderBridgeStatus(ip = "", paired = false, interrupted = false) {
    const updating =
      snapshot.activeOperation?.name === "firmware.install" &&
      snapshot.activeOperation.state === "running";
    // Keep the last-known OTA progress visible through a transport interruption.
    // All controls remain disabled until the helper reconnects.
    $("bridge-offline").hidden = connected || updating;
    $("bridge-online").hidden = !connected && !updating;
    $("bridge-connection").classList.toggle("is-offline", !connected);
    $("bridge-status-text").textContent = connected
      ? `Python Bridge Connected From: ${ip || "Unknown"}${snapshot.simulated ? " · DEMONSTRATION — NO HARDWARE" : ""}`
      : `Python Bridge Not Connected${interrupted ? " · Reconnecting To Server" : ""}`;
    $("revoke-bridge").hidden = !connected && !paired;
    if (connected) {
      // The invitation is consumed. Discard its UI and any copy feedback so it
      // cannot reappear after a later disconnect or an asynchronous clipboard reply.
      $("bridge-invitation").value = "";
      $("invitation-label").hidden = true;
      $("copy-invitation").hidden = true;
      notices.get("invitation")?.();
    }
  }
  function connectSocket() {
    socket = new WebSocket(
      `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/bridge/ui/socket`,
    );
    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.kind === "ready") clientId = data.clientId;
      if (data.kind === "ready" || data.kind === "connection") {
        connected = data.connected;
        if (data.snapshot) snapshot = data.snapshot;
        renderBridgeStatus(data.ip, !!data.helperId);
        if (!selectedArtifact && snapshot.artifacts?.length) {
          const artifact = snapshot.artifacts
            .filter((a) => a.model === model())
            .at(-1);
          if (artifact) showFirmware(artifact);
        }
        renderIdentity();
        renderCandidates(snapshot.candidates);
        if (connected || snapshot.activeOperation?.state === "running")
          renderOperation(snapshot.activeOperation);
        updateControls();
      }
      if (data.kind === "operation") {
        snapshot.activeOperation = data.operation;
        renderOperation(data.operation);
        updateControls();
      }
      if (data.kind === "candidate") {
        const candidates = snapshot.candidates || [];
        const index = candidates.findIndex(
          (c) => c.deviceId === data.candidate.deviceId,
        );
        if (index < 0) candidates.push(data.candidate);
        else candidates[index] = data.candidate;
        snapshot.candidates = candidates;
        renderCandidates(candidates);
      }
      if (data.kind === "accepted" && data.name === "firmware.install")
        renderOperation(data.progress);
      if (data.kind === "progress") {
        const p = data.progress;
        progressMessage(
          `${p.stage.replaceAll("_", " ")} ${p.bytesTotal ? `· ${Math.round((p.bytesDone / p.bytesTotal) * 100)}%` : ""}`,
        );
        $("operation-progress").hidden = !p.bytesTotal;
        if (p.bytesTotal)
          $("operation-progress").value = p.bytesDone / p.bytesTotal;
      }
      const waiting = pending.get(data.id);
      if (waiting && ["result", "error"].includes(data.kind)) {
        pending.delete(data.id);
        clearTimeout(waiting.timer);
        if (data.kind === "error")
          waiting.reject(new Error(data.error.message));
        else waiting.resolve(data.result);
      }
    };
    socket.onclose = () => {
      clientId = null;
      connected = false;
      updateControls();
      renderBridgeStatus("", false, true);
      if (snapshot.activeOperation?.state === "running")
        renderOperation(snapshot.activeOperation);
      for (const [id, task] of pending) {
        // Preserve the wait for this OTA, not its request. The reconnect
        // snapshot resolves it; START and firmware bytes are never resent.
        if (task.name === "firmware.install") continue;
        clearTimeout(task.timer);
        task.reject(
          new Error(
            "Browser connection interrupted. Any active OTA continues in the Python bridge; reconnect before issuing another command.",
          ),
        );
        pending.delete(id);
      }
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connectSocket, 2500);
    };
  }
  function renderOperation(operation) {
    if (!operation || operation.name !== "firmware.install") return;
    if (operation.state === "running") {
      const total = operation.bytesTotal || selectedArtifact?.size;
      const done = operation.bytesDone || 0;
      progressMessage(
        `${connected ? "Firmware Update" : "Reconnecting · Last Reported Update Progress"} · ${(operation.stage || "starting").replaceAll("_", " ")}${total ? ` · ${Math.round((done / total) * 100)}%` : ""}`,
      );
      $("operation-progress").hidden = false;
      if (total) $("operation-progress").value = done / total;
      else $("operation-progress").removeAttribute("value");
      return;
    }
    if (!["complete", "failed", "cancelled"].includes(operation.state)) return;
    const error =
      operation.error?.message ||
      "Firmware Transfer Did Not Complete. Check The Bridge Terminal.";
    progressMessage(
      operation.state === "complete"
        ? "Firmware Transfer Complete · Reconnect To Confirm The Running Version"
        : error,
      operation.state !== "complete",
    );
    $("operation-progress").hidden = operation.state !== "complete";
    $("operation-progress").value = 1;
    for (const [id, task] of pending) {
      if (
        task.name !== "firmware.install" ||
        task.operationId !== operation.operationId
      )
        continue;
      pending.delete(id);
      clearTimeout(task.timer);
      if (operation.state === "complete") task.resolve(operation.result);
      else task.reject(new Error(error));
    }
  }
  async function action(
    callback,
    { interruptScan = false, transientProgress = false } = {},
  ) {
    if (busy && !(interruptScan && scanInProgress)) return;
    const sequence = ++actionSequence;
    if (interruptScan && scanInProgress) {
      scanInProgress = false;
      scanStatus("stopped");
    }
    busy = true;
    if (transientProgress) $("operation-status").hidden = true;
    updateControls();
    try {
      await callback();
    } catch (error) {
      if (sequence === actionSequence) message(error.message, true);
    } finally {
      // The interrupted scan can finish while Connect is still running. Its
      // completion must not re-enable controls or replace the new action's UI.
      if (sequence !== actionSequence) return;
      if (transientProgress) $("operation-status").hidden = true;
      busy = false;
      updateControls();
      renderCandidates(snapshot.candidates);
    }
  }
  async function refreshKnown() {
    knownDevices = (await api("/api/devices")).devices;
  }
  function offerEnrollment() {
    const d = snapshot.device;
    if (
      d &&
      d.supported !== false &&
      d.capabilities?.enrollment !== false &&
      !knownDevices.some((s) => s.mac === d.mac) &&
      !prompted.has(d.mac)
    ) {
      prompted.add(d.mac);
      $("device-label").value = `${label(d.model)} ${d.mac.slice(-4)}`;
      $("enroll-description").textContent =
        snapshot.device?.model === "WBS13"
          ? "Save this Body Smart, then choose its local users in Scales → Edit Settings. Withings user import is unavailable for this model."
          : "Save this scale and check Withings for existing users and settings. You choose which new users to import.";
      $("enroll-dialog").showModal();
    }
  }
  function showRoster(result) {
    migration = result;
    $("roster-users").replaceChildren();
    $("roster-message").textContent = result.migrationIncomplete
      ? result.message
      : `${result.settingsReady ? "Device settings are ready. " : "Settings import needs a retry. "}${result.users.length ? "Choose new users to import." : "All known users are already imported."}`;
    for (const user of result.users) {
      const label = document.createElement("label"),
        input = document.createElement("input");
      input.type = "checkbox";
      input.value = user.id;
      input.checked = true;
      label.append(
        input,
        document.createTextNode(
          `${user.name} · ${user.shortName} · ${user.heightCm} cm · ${user.weightKg.toFixed(2)} kg`,
        ),
      );
      $("roster-users").append(label);
    }
    $("confirm-roster").hidden = !result.users.length;
    $("roster-dialog").showModal();
  }
  function showFirmware(artifact) {
    selectedArtifact = artifact;
    const classification = unknownFirmware(artifact)
      ? "Unknown Firmware"
      : artifact.classification === "known_stock"
        ? "Known Stock Firmware"
        : "Known YOW Release";
    $("firmware-info").hidden = false;
    $("firmware-info").textContent =
      `${artifact.filename} · v${artifact.version} · ${artifact.size.toLocaleString()} Bytes · ${classification}\nSHA-256: ${artifact.sha256}`;
    $("firmware-warning").hidden = !unknownFirmware(artifact);
    $("firmware-warning").textContent = unknownFirmwareWarning;
    $("download-firmware").hidden = false;
    updateControls();
  }
  function download(data, name, type) {
    const url = URL.createObjectURL(new Blob([data], { type })),
      link = document.createElement("a");
    link.href = url;
    link.download = name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  }
  async function clock() {
    return api(
      `/api/config/time?zone=${encodeURIComponent($("scale-timezone").value || "UTC")}`,
    );
  }
  function watchContact() {
    clearInterval(contactTimer);
    const scale = knownDevices.find((s) => s.mac === snapshot.device?.mac);
    if (!scale) return;
    const start = Math.floor(Date.now() / 1000);
    let attempts = 0;
    contactTimer = setInterval(async () => {
      try {
        const status = await api(`/api/scales/${scale.id}/connection-status`);
        if (status.last_session_at >= start) {
          $("wifi-status").textContent =
            "Server Contact Confirmed · Authenticated Wi-Fi Session Received";
          clearInterval(contactTimer);
        }
      } catch {
        /* A browser reconnect must not affect device operations. */
      }
      if (++attempts >= 30) clearInterval(contactTimer);
    }, 2000);
  }
  $("new-invitation").onclick = () =>
    action(async () => {
      const invitation = await api("/api/bridge/invitations", {});
      $("bridge-invitation").value = JSON.stringify(invitation);
      $("invitation-label").hidden = false;
      $("copy-invitation").hidden = false;
    });
  $("copy-invitation").onclick = () =>
    navigator.clipboard.writeText($("bridge-invitation").value).then(
      () => {
        if (!connected) message("Invitation Copied", false, "invitation");
      },
      () => {
        if (connected) return;
        $("bridge-invitation").select();
        message("Select And Copy The Invitation", false, "invitation");
      },
    );
  $("revoke-bridge").onclick = () =>
    action(async () => {
      await api("/api/bridge/revoke", {});
      // The header shows the new state; do not leave a second disconnect notice
      // below the invitation panel when the workspace switches to offline.
      $("operation-status").hidden = true;
    });
  async function scan(scaleModel) {
    await action(async () => {
      const sequence = actionSequence;
      $("scale-model").value = scaleModel;
      snapshot.candidates = [];
      renderCandidates([]);
      scanInProgress = true;
      scanStatus("scanning");
      try {
        const r = await command("device.scan.start", {
          model: scaleModel,
          durationSeconds: 15,
        });
        snapshot.candidates = r.candidates;
        if (sequence === actionSequence) scanStatus("complete");
        if (sequence === actionSequence && !r.candidates.length)
          message(
            "No Scale Found. Check Setup Mode And Terminal Bluetooth Permission.",
          );
      } catch (error) {
        if (sequence === actionSequence) scanStatus("interrupted");
        throw error;
      } finally {
        if (sequence === actionSequence) scanInProgress = false;
      }
    });
  }
  $("scan-ble").onclick = () => scan("WBS06");
  $("scan-classic").onclick = () => scan("WBS03");
  $("disconnect").onclick = () =>
    action(async () => {
      await command("device.disconnect");
      snapshot = { ...snapshot, state: "disconnected", device: null };
      renderIdentity();
      message("Scale Disconnected");
    });
  $("probe").onclick = () => action(identify);
  $("complete-setup").onclick = () =>
    action(async () => {
      watchContact();
      await command("device.complete_setup");
      message(
        "Setup Completed. The Scale May Now Disconnect And Sync Over Wi-Fi.",
      );
    });
  $("reveal-secret").onclick = () =>
    action(async () => {
      $("device-secret").textContent = (
        await command("device.reveal_secret")
      ).secret;
      $("device-secret").hidden = false;
      $("reveal-secret").hidden = true;
    });
  $("check-firmware-offer").onclick = () =>
    action(async () => {
      const d = snapshot.device;
      if (!d || d.supported !== false)
        throw new Error("Connect and identify an unrecognised scale first");
      if (d.capabilities?.vendorFirmwareOfferRead === false)
        throw new Error(
          "This model requires a separate client-certificate firmware lookup",
        );
      if (d.secretAvailable === false)
        throw new Error(
          "The scale did not provide the secret required for a firmware lookup",
        );
      const modelCode = $("offer-model-code").value.trim().toUpperCase();
      const currentFirmware = Number($("offer-reported-version").value);
      const manufacturerId = Number($("offer-manufacturer-id").value || 0);
      if (!/^[A-Z]{2,4}\d{2}$/.test(modelCode))
        throw new Error(
          "Enter the model code printed on the scale, such as WBS08",
        );
      if (
        !Number.isInteger(currentFirmware) ||
        currentFirmware < 0 ||
        currentFirmware > 65535
      )
        throw new Error("Enter a firmware version between 0 and 65535");
      if (
        !Number.isInteger(manufacturerId) ||
        manufacturerId < 0 ||
        manufacturerId > 2147483647
      )
        throw new Error("Enter a valid manufacturer ID or leave it at 0");
      message("Checking Withings Firmware Offer…");
      const { secret } = await command("device.reveal_secret");
      const result = await api("/api/firmware/offer", {
        mac: d.mac,
        secret,
        modelCode,
        currentFirmware,
        manufacturerId,
      });
      $("offer-url").textContent = result.offered
        ? result.url
        : "No update offered for these request values";
      $("offer-hash").textContent = result.offered ? result.sha1 : "—";
      $("firmware-offer-result").hidden = false;
      offerReport = [
        `Model code: ${modelCode}`,
        `Transport: ${d.model === "WBS03" ? "Bluetooth Classic" : "BLE"}`,
        `Probed firmware: ${d.firmwareVersion}`,
        `Reported firmware: ${currentFirmware}`,
        `Bootloader: ${d.bootloaderVersion}`,
        `Hardware field: ${d.hardwareVersion}`,
        `Manufacturer ID supplied: ${manufacturerId}`,
        `Firmware URL: ${result.offered ? result.url : "No update offered"}`,
        `SHA-1: ${result.offered ? result.sha1 : "Not supplied"}`,
      ].join("\n");
      message(
        result.offered
          ? "Firmware Offer Found"
          : "No Firmware Offer For These Values",
      );
    });
  $("copy-firmware-offer").onclick = () => {
    if (!offerReport) return;
    navigator.clipboard.writeText(offerReport).then(
      () => message("GitHub Issue Details Copied"),
      () =>
        message(
          "Could Not Copy Details. Use The Displayed URL And SHA-1.",
          true,
        ),
    );
  };
  for (const id of [
    "offer-model-code",
    "offer-reported-version",
    "offer-manufacturer-id",
  ])
    $(id).addEventListener("input", () => {
      offerReport = "";
      $("firmware-offer-result").hidden = true;
    });
  $("import-device").onclick = () => {
    $("device-label").value =
      `${label(model())} ${snapshot.device.mac.slice(-4)}`;
    $("enroll-description").textContent =
      snapshot.device?.model === "WBS13"
        ? "Save this Body Smart, then choose its local users in Scales → Edit Settings. Withings user import is unavailable for this model."
        : "Save this scale and check Withings for existing users and settings. You choose which new users to import.";
    $("enroll-dialog").showModal();
  };
  $("confirm-enroll").onclick = () =>
    action(async () => {
      $("enroll-dialog").close();
      message("Reading Device Settings And Importing From Withings…");
      const result = await command("device.enroll", {
        approved: true,
        label: $("device-label").value,
        timeZone: $("scale-timezone").value,
      });
      const preview = await api("/api/scales/enroll", {
        ...result,
        label: $("device-label").value,
      });
      await refreshKnown();
      if (preview.localRoster) {
        window.location.href = `/scales#scale-${preview.scaleId}`;
      } else {
        showRoster(preview);
        message("Device Saved On Server");
      }
    });
  $("export-device").onclick = () =>
    action(async () => {
      const r = await command("device.enroll", {
        approved: true,
        label: "",
        timeZone: $("scale-timezone").value,
      });
      download(
        JSON.stringify(r.device, null, 2),
        `${model().toLowerCase()}.yow-device.json`,
        "application/json",
      );
      message("Private Device Export Downloaded");
    });
  $("confirm-roster").onclick = () =>
    action(async () => {
      const userIds = [
        ...$("roster-users").querySelectorAll("input:checked"),
      ].map((x) => Number(x.value));
      await api(`/api/scales/${migration.scaleId}/import-users`, {
        digest: migration.digest,
        userIds,
      });
      $("roster-dialog").close();
      location.assign("/firmware");
    });
  $("generate-firmware").onclick = () =>
    action(
      async () => {
        showFirmware(await command("firmware.generate", { model: model() }));
        message("Firmware Generated And Verified");
      },
      { transientProgress: true },
    );
  $("manual-firmware").onchange = () =>
    action(
      async () => {
        const file = $("manual-firmware").files[0];
        if (!file) return;
        // Failed inspection must not leave a previously selected image ready to flash.
        selectedArtifact = null;
        $("firmware-info").hidden = true;
        $("firmware-warning").hidden = true;
        $("download-firmware").hidden = true;
        $("manual-firmware").value = "";
        updateControls();
        if (file.size > 2 * 1024 * 1024)
          throw new Error("Firmware exceeds the 2 MiB limit");
        const data = new Uint8Array(await file.arrayBuffer());
        const sha = [
          ...new Uint8Array(await crypto.subtle.digest("SHA-256", data)),
        ]
          .map((x) => x.toString(16).padStart(2, "0"))
          .join("");
        const { transferId } = await command("artifact.begin", {
          filename: file.name,
          size: data.length,
          sha256: sha,
          model: model(),
        });
        for (let offset = 0; offset < data.length; offset += 32768) {
          const chunk = data.subarray(offset, offset + 32768);
          await command("artifact.chunk", {
            transferId,
            offset,
            dataBase64: btoa(String.fromCharCode(...chunk)),
          });
          progressMessage(
            `Sending Image To Local Bridge · ${Math.round(((offset + chunk.length) / data.length) * 100)}%`,
          );
          $("operation-progress").hidden = false;
          $("operation-progress").value = (offset + chunk.length) / data.length;
        }
        showFirmware(await command("artifact.finish", { transferId }));
        message(
          unknownFirmware(selectedArtifact)
            ? "Unknown Firmware Selected · Review The Warning Before Installing"
            : "Manual Image Validated",
        );
      },
      { transientProgress: true },
    );
  $("install-firmware").onclick = () => {
    if (!selectedArtifact) return;
    flashArtifact = selectedArtifact;
    $("flash-title").textContent = unknownFirmware(flashArtifact)
      ? "Install Unknown Firmware?"
      : "Install Firmware?";
    $("flash-warning").hidden = !unknownFirmware(flashArtifact);
    $("flash-warning").textContent = unknownFirmwareWarning;
    $("flash-summary").textContent =
      `${flashArtifact.filename} · v${flashArtifact.version} → ${label(model())} · ${snapshot.device.mac}\nSHA-256: ${flashArtifact.sha256}`;
    $("flash-prompt").textContent = `Type ${flashPhrase(flashArtifact)}`;
    $("flash-confirmation").value = "";
    $("confirm-flash").disabled = true;
    $("flash-dialog").showModal();
  };
  $("flash-confirmation").oninput = () => {
    $("confirm-flash").disabled =
      !flashArtifact ||
      $("flash-confirmation").value !== flashPhrase(flashArtifact);
  };
  $("confirm-flash").onclick = () =>
    action(async () => {
      const artifact = flashArtifact;
      if (!artifact || artifact !== selectedArtifact)
        throw new Error("Select the firmware again before confirming");
      const confirmation = flashPhrase(artifact);
      if ($("flash-confirmation").value !== confirmation)
        throw new Error(`Type ${confirmation} to confirm`);
      $("flash-dialog").close();
      const result = await command("firmware.install", {
        artifactId: artifact.artifactId,
        sha256: artifact.sha256,
        confirmation,
      });
      snapshot.device = null;
      renderIdentity();
      message(
        result.transferred
          ? "Transfer Complete. Reconnect To Confirm The Running Firmware."
          : "Update Outcome Unconfirmed",
      );
    });
  $("download-firmware").onclick = () =>
    action(async () => {
      let offset = 0,
        parts = [];
      do {
        const r = await command("artifact.read", {
          artifactId: selectedArtifact.artifactId,
          offset,
        });
        parts.push(Uint8Array.from(atob(r.dataBase64), (c) => c.charCodeAt(0)));
        offset = r.nextOffset;
        if (r.done) break;
      } while (offset < selectedArtifact.size);
      download(
        new Blob(parts),
        selectedArtifact.filename,
        "application/octet-stream",
      );
      message("Firmware Downloaded");
    });
  $("read-configuration").onclick = () =>
    action(async () => {
      const r = await command("device.read_configuration");
      const errors = [],
        status = [];
      // A successful empty read is different from a failed read. Preserve
      // entered values on failure and show the bridge's actual explanation.
      if (r.server.available === false) {
        errors.push(`Server: ${r.server.error || "Read Timed Out"}`);
      } else if (!r.server.supported) {
        status.push("Custom Server Read Not Supported");
      } else {
        $("server-host").value = r.server.host || "";
        $("server-host").placeholder = r.server.unset
          ? "Not Configured"
          : "scales.example.com";
        if (r.server.transport)
          $("server-transport").value = r.server.transport;
        status.push(
          r.server.unset
            ? "Custom Server Not Configured"
            : "Server Settings Read",
        );
      }
      if (r.wifi.available === false) {
        errors.push(`Wi-Fi: ${r.wifi.error || "Read Timed Out"}`);
        $("wifi-status").textContent = "Wi-Fi Read Failed";
      } else if (!r.wifi.supported) {
        status.push("Wi-Fi Read Not Supported");
      } else {
        $("wifi-ssid").value = r.wifi.ssid || "";
        $("wifi-ssid").placeholder = r.wifi.ssid ? "" : "Not Configured";
        $("wifi-password").value = "";
        $("wifi-password").placeholder = r.wifi.ssid ? "••••••" : "";
        $("wifi-password-hint").textContent = r.wifi.ssid
          ? "A network is stored. The password is not exposed; enter it to save or reconnect."
          : "Enter the network name and password to configure Wi-Fi.";
        $("wifi-status").textContent = r.wifi.ssid
          ? "Stored SSID Read · Connection Not Tested"
          : "Wi-Fi Not Configured";
        status.push(
          r.wifi.ssid ? "Wi-Fi Settings Read" : "Wi-Fi Not Configured",
        );
      }
      message([...errors, ...status].join(" · "), errors.length > 0);
    });
  $("use-this-host").onclick = () => {
    $("server-host").value = location.hostname.replace(/^\[|\]$/g, "");
    if (["localhost", "127.0.0.1", "::1"].includes(location.hostname))
      message(
        "Use This Computer’s LAN Address For The Scale; localhost Would Point Back To The Scale.",
        true,
      );
  };
  $("server-form").onsubmit = (e) => {
    e.preventDefault();
    action(async () => {
      const r = await command("device.set_server", {
        host: $("server-host").value,
        transport: $("server-transport").value,
      });
      $("server-host").placeholder = "scales.example.com";
      message(`Stored Server: ${r.transport.toUpperCase()} ${r.host}`);
    });
  };
  $("wifi-ssid").addEventListener("input", () => {
    $("wifi-password").value = "";
    $("wifi-password").placeholder = "";
    $("wifi-password-hint").textContent =
      "Network changed. Enter its Wi-Fi password before saving.";
    $("wifi-status").textContent = "";
  });
  $("wifi-form").onsubmit = (e) => {
    e.preventDefault();
    action(async () => {
      const password = $("wifi-password").value;
      if (!password)
        throw new Error("Enter the Wi-Fi password before saving this network.");
      $("wifi-password").value = "";
      watchContact();
      const r = await command("device.connect_wifi", {
        ssid: $("wifi-ssid").value,
        password,
      });
      $("wifi-password").placeholder =
        r.joinStatus === "success" ? "••••••" : "";
      $("wifi-status").textContent =
        r.joinStatus === "success"
          ? "Wi-Fi Connected · Device Reported Success"
          : "Wi-Fi Connection Failed · Check Credentials And 2.4 GHz WPA2 Network";
      message(
        r.storedSsidMatches
          ? "SSID Readback Matches. Use Complete Setup To Start Normal Operation."
          : "SSID Readback Did Not Match",
        !r.storedSsidMatches,
      );
    });
  };
  $("set-time").onclick = () =>
    action(async () => {
      await command("device.set_time", await clock());
      const scale = knownDevices.find((s) => s.mac === snapshot.device?.mac);
      if (scale) {
        await api(`/api/scales/${scale.id}/time-zone`, {
          timeZone: $("scale-timezone").value || "UTC",
        });
      }
      message(
        scale
          ? "Scale Clock Set · Time Zone Saved For Future Syncs"
          : "Scale Clock Set",
      );
    });
  $("scale-model").onchange = () => {
    snapshot = { ...snapshot, device: null, candidates: [] };
    selectedArtifact = null;
    $("firmware-info").hidden = true;
    $("firmware-warning").hidden = true;
    $("download-firmware").hidden = true;
    renderCandidates([]);
    updateControls();
  };
  refreshKnown().catch((error) => message(error.message, true));
  connectSocket();
  updateControls();
})();
