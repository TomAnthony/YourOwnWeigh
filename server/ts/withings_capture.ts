/** Read-only vendor migration over ordinary, publicly verified HTTPS.
 * Shared by Node and Cloudflare. Never disable verification or fall back to HTTP.
 */
import {
  captureWithingsSession,
  lookupWithingsFirmware,
  type FirmwareLookupIdentity,
} from "./withings_protocol.ts";
export const WITHINGS_ORIGIN = "https://scalews.withings.net";
const MAX_RESPONSE = 2_000_000;

export async function withingsPost(
  path: string,
  fields: string,
  fetcher: typeof fetch = fetch,
  query: { appName: string; currentFirmware: number } = {
    appName: "WBS06",
    currentFirmware: 1181,
  },
): Promise<Record<string, any>> {
  if (!["once", "session", "v2/screen", "v2/summary"].includes(path))
    throw new Error("Unsupported migration endpoint");
  if (
    !/^[A-Z]{2,4}[0-9]{2}$/.test(query.appName) ||
    !Number.isInteger(query.currentFirmware) ||
    query.currentFirmware < 0 ||
    query.currentFirmware > 65535
  )
    throw new Error("Invalid scale model or firmware version");
  const response = await fetcher(
    `${WITHINGS_ORIGIN}/${path}?appliver=${query.currentFirmware}&appname=${query.appName}&apppfm=device`,
    {
      method: "POST",
      redirect: "error",
      signal: AbortSignal.timeout(15000),
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "Cache-Control": "no-store",
      },
      body: fields,
    },
  );
  if (response.status !== 200) {
    await response.body?.cancel();
    throw new Error(`Withings ${path} returned HTTP ${response.status}`);
  }
  if (Number(response.headers.get("Content-Length") ?? 0) > MAX_RESPONSE) {
    await response.body?.cancel();
    throw new Error("Withings response is oversized");
  }
  const reader = response.body?.getReader();
  if (!reader) throw new Error("Withings returned an empty response");
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > MAX_RESPONSE) {
        await reader.cancel();
        throw new Error("Withings response is oversized");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  let document: Record<string, any>;
  try {
    document = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    throw new Error(`Withings ${path} returned non-JSON data`);
  }
  if (
    !document ||
    document.status !== 0 ||
    !document.body ||
    typeof document.body !== "object"
  ) {
    throw new Error(`Withings ${path} returned an unsuccessful response`);
  }
  return document;
}
  // Identify the session as the actual model so the query string (appname /
  // appliver) and the session form agree. Body Cardio ships stock 2231.
  const query =
    scale.model === "WBS04"
      ? { appName: "WBS04", currentFirmware: 2231 }
      : { appName: "WBS06", currentFirmware: 1181 };
  return captureWithingsSession(scale, (path, fields) =>
    withingsPost(path, fields, fetch, query),
  );

export const firmwareOffer = (identity: Record<string, any>) =>
  lookupWithingsFirmware(identity as FirmwareLookupIdentity, (path, fields) =>
    withingsPost(path, fields, fetch, {
      appName: identity.modelCode,
      currentFirmware: identity.currentFirmware,
    }),
  );
