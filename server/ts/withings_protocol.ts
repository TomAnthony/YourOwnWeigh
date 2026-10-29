/** Read-only migration exchange for both scale identities, shared by Node and Worker. */
type ScaleIdentity = Record<string, any>;
export type WithingsPost = (
  path: string,
  fields: string,
) => Promise<Record<string, any>>;
export type FirmwareLookupIdentity = {
  mac: string;
  secret: string;
  modelCode: string;
  currentFirmware: number;
  manufacturerId?: number;
};
const enc = new TextEncoder();
const form = (values: Record<string, string | number>) =>
  new URLSearchParams(
    Object.entries(values).map(([key, value]) => [key, String(value)]),
  ).toString();
async function sha(value: string): Promise<string> {
  return Array.from(
    new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(value))),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");
}

/** Ask only for the firmware offer. Never retain the vendor session, roster,
 * device secret, or complete response in the report shown to the user. */
export async function lookupWithingsFirmware(
  identity: FirmwareLookupIdentity,
  post: WithingsPost,
): Promise<{ offered: boolean; url?: string; sha1?: string }> {
  const rawMac = identity.mac?.replace(/[:-]/g, "").toLowerCase();
  if (
    !/^[0-9a-f]{12}$/.test(rawMac ?? "") ||
    !/^[0-9a-f]{16}$/i.test(identity.secret ?? "") ||
    !/^[A-Z]{2,4}[0-9]{2}$/.test(identity.modelCode ?? "") ||
    !Number.isInteger(identity.currentFirmware) ||
    identity.currentFirmware < 0 ||
    identity.currentFirmware > 65535 ||
    !Number.isInteger(identity.manufacturerId ?? 0) ||
    (identity.manufacturerId ?? 0) < 0 ||
    (identity.manufacturerId ?? 0) > 0x7fffffff
  )
    throw new Error("Invalid scale identity or firmware lookup values");
  const mac = rawMac!.match(/.{2}/g)!.join(":");
  const challenge = (await post("once", "action=get")).body?.once;
  if (
    typeof challenge !== "string" ||
    challenge.length < 1 ||
    challenge.length > 31
  )
    throw new Error("Withings challenge is invalid");
  const body = (
    await post(
      "session",
      form({
        action: "new",
        auth: mac,
        hash: await sha(`${mac}:${identity.secret}:${challenge}`),
        mfgid: identity.manufacturerId ?? 0,
        currentfw: identity.currentFirmware,
        batterylvl: 100,
        duration: 300,
        wstarget: 1,
        enrich: "t",
        trademark: 1,
        network: 1,
        hashmethod: "sha256",
        trigger: "weather",
        withaccids: 1,
        feature_mask: 0,
      }),
    )
  ).body;
  const url = body?.syp?.blc;
  const hash = body?.syp?.sha1;
  if (url == null && hash == null) return { offered: false };
  if (
    typeof url !== "string" ||
    url.length > 1024 ||
    typeof hash !== "string" ||
    !/^[a-f0-9]{40}$/i.test(hash)
  )
    throw new Error("Withings returned an incomplete firmware offer");
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error("Withings returned an invalid firmware URL");
  }
  if (
    !["http:", "https:"].includes(parsed.protocol) ||
    !parsed.hostname.endsWith(".withings.net") ||
    parsed.username ||
    parsed.password
  )
    throw new Error("Withings returned an unexpected firmware URL");
  return { offered: true, url, sha1: hash.toLowerCase() };
}

export async function captureWithingsSession(
  scale: ScaleIdentity,
  post: WithingsPost,
): Promise<string> {
  const mac =
    String(scale.mac ?? "")
      .replace(/[:-]/g, "")
      .toLowerCase()
      .match(/.{2}/g)
      ?.join(":") ?? "";
  if (!/^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$/.test(mac) || !scale.secret)
    throw new Error("Scale MAC or secret is missing");
  const once = (await post("once", "action=get")).body.once;
  if (typeof once !== "string" || once.length < 1 || once.length > 31)
    throw new Error("Withings challenge is invalid");
  const hash = await sha(`${mac}:${scale.secret}:${once}`);
  const session = (
    await post(
      "session",
      form({
        action: "new",
        auth: mac,
        hash,
        mfgid: scale.reported_mfgid ?? 0,
        currentfw: 1181,
        batterylvl: 100,
        duration: 300,
        wstarget: 1,
        enrich: "t",
        trademark: 1,
        network: 1,
        hashmethod: "sha256",
        trigger: "weather",
        withaccids: 1,
        feature_mask: scale.reported_feature_mask ?? 0,
      }),
    )
  ).body;
  const sessionid = session.sessionid;
  if (
    typeof sessionid !== "string" ||
    sessionid.length < 1 ||
    sessionid.length > 31
  )
    throw new Error("Withings session is invalid");
  const responses = await Promise.allSettled([
    post("v2/screen", form({ short: 1, action: "getbydeviceid", sessionid })),
    post("v2/summary", form({ action: "getforscale", sessionid })),
  ]);
  // A display endpoint outage must not discard an already retrieved roster.
  // WBS06 remains marked incomplete until both required fixtures are present;
  // WS-30 never uses these WBS06 display responses.
  const screen =
    responses[0].status === "fulfilled" ? responses[0].value : null;
  const summary =
    responses[1].status === "fulfilled" ? responses[1].value : null;
  return JSON.stringify({
    format: "WBS06-Withings-readonly-baseline-v1",
    mac: scale.mac,
    ctp: session.ctp,
    ind: session.ind,
    sp: session.sp,
    screen_response: screen,
    summary_response: summary,
    weather_response: null,
  });
}
