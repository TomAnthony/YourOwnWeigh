/** Last observed running firmware, independent of the original device export.
 * This is a device report, not a measurement of either external flash slot.
 */
export function firmwareVersion(value: unknown): number | null {
  if (typeof value === "string" && !/^\d{1,8}$/.test(value)) return null;
  if (typeof value !== "number" && typeof value !== "string") return null;
  const version = Number(value);
  return Number.isInteger(version) && version > 0 && version < 0xffffff
    ? version
    : null;
}

/** Both scale families send currentfw at session creation. WBS06 also sends
 * appliver in the URL. Ignore ambiguous/malformed reports without breaking sync.
 */
export function sessionFirmware(
  params: URLSearchParams,
  model: string,
): number | null {
  const names = params.getAll("appname");
  if (names.length > 1 || (names.length === 1 && names[0] !== model))
    return null;
  const current = params.getAll("currentfw"),
    app = params.getAll("appliver");
  if (current.length > 1 || app.length > 1) return null;
  if (current.length) {
    const version = firmwareVersion(current[0]);
    if (app.length && firmwareVersion(app[0]) !== version) return null;
    return version;
  }
  return app.length === 1 && names[0] === model
    ? firmwareVersion(app[0])
    : null;
}

/** A delayed import/probe must not overwrite a more recent Wi-Fi observation.
 * sessionToken gates Wi-Fi writes on the session actually being issued in the
 * same transaction (a consumed challenge/replay must never refresh this row).
 */
export function firmwareObservation(
  db: D1Database,
  id: number,
  version: number,
  observedAt: number,
  source: "bluetooth" | "wifi",
  sessionToken?: string,
): D1PreparedStatement {
  const now = Math.floor(Date.now() / 1000);
  if (
    firmwareVersion(version) === null ||
    !Number.isSafeInteger(observedAt) ||
    observedAt < 1 ||
    observedAt > now + 300
  )
    throw new Error("Invalid firmware observation");
  const timestamp = Math.min(observedAt, now); // Allow small bridge clock skew.
  const guard = sessionToken
    ? " AND EXISTS (SELECT 1 FROM device_sessions WHERE token=? AND scale_id=scales.id)"
    : "";
  return db
    .prepare(
      "UPDATE scales SET firmware_version=?,firmware_confirmed_at=?,firmware_source=? " +
        "WHERE id=? AND (firmware_confirmed_at IS NULL OR firmware_confirmed_at<=?)" +
        guard,
    )
    .bind(
      version,
      timestamp,
      source,
      id,
      timestamp,
      ...(sessionToken ? [sessionToken] : []),
    );
}
