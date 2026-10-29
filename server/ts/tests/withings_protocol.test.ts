import test from "node:test";
import assert from "node:assert/strict";
import {
  captureWithingsSession,
  lookupWithingsFirmware,
} from "../withings_protocol.ts";

test("read-only Withings capture authenticates the device and stages its roster", async () => {
  const calls: string[] = [];
  const posted = async (
    path: string,
    fields: string,
  ): Promise<Record<string, any>> => {
    calls.push(path);
    const form = new URLSearchParams(fields);
    if (path === "once")
      return { status: 0, body: { once: "fixed-challenge" } };
    if (path === "session") {
      assert.equal(form.get("action"), "new");
      assert.equal(form.get("auth"), "24:e4:2f:12:34:56");
      assert.equal(form.get("hashmethod"), "sha256");
      assert.match(form.get("hash") ?? "", /^[0-9a-f]{64}$/);
      assert.equal(form.get("hash")?.includes("device-secret"), false);
      return {
        status: 0,
        body: {
          sessionid: "session-1",
          sp: { users: [{ id: 17, sn: "SAM" }] },
          ctp: { goff: 0 },
          ind: { w: 1 },
        },
      };
    }
    assert.equal(form.get("sessionid"), "session-1");
    return { status: 0, body: path === "v2/summary" ? [] : { device: [] } };
  };
  const raw = await captureWithingsSession(
    { mac: "24E42F123456", secret: "device-secret" },
    posted,
  );
  const captured = JSON.parse(raw);
  assert.deepEqual(calls, ["once", "session", "v2/screen", "v2/summary"]);
  assert.equal(captured.format, "WBS06-Withings-readonly-baseline-v1");
  assert.equal(captured.sp.users[0].id, 17);
  assert.equal(raw.includes("device-secret"), false);
});

test("firmware lookup makes only the read-only challenge/session exchange and returns a shareable offer", async () => {
  const calls: string[] = [];
  const identity = {
    mac: "020000000008",
    secret: "0123456789abcdef",
    modelCode: "WBS08",
    currentFirmware: 1179,
    manufacturerId: 1622096,
  };
  const result = await lookupWithingsFirmware(
    identity,
    async (path, fields) => {
      calls.push(path);
      if (path === "once") return { status: 0, body: { once: "challenge" } };
      const form = new URLSearchParams(fields);
      assert.equal(form.get("auth"), "02:00:00:00:00:08");
      assert.equal(form.get("currentfw"), "1179");
      assert.equal(form.get("mfgid"), "1622096");
      assert.match(form.get("hash") ?? "", /^[0-9a-f]{64}$/);
      return {
        status: 0,
        body: {
          sessionid: "private",
          sp: { users: [{ name: "private" }] },
          syp: {
            blc: "http://cdnfw.withings.net/wbs08/wbs08_1181.bin",
            sha1: "a".repeat(40),
          },
        },
      };
    },
  );
  assert.deepEqual(calls, ["once", "session"]);
  assert.deepEqual(result, {
    offered: true,
    url: "http://cdnfw.withings.net/wbs08/wbs08_1181.bin",
    sha1: "a".repeat(40),
  });
  assert.equal(JSON.stringify(result).includes(identity.secret), false);
  assert.equal(JSON.stringify(result).includes("private"), false);
});

test("firmware lookup handles no offer and rejects incomplete vendor metadata", async () => {
  const identity = {
    mac: "020000000008",
    secret: "0123456789abcdef",
    modelCode: "WBS08",
    currentFirmware: 1181,
  };
  const poster = (body: Record<string, any>) => async (path: string) =>
    path === "once" ? { body: { once: "challenge" } } : { body };
  assert.deepEqual(
    await lookupWithingsFirmware(identity, poster({ syp: {} })),
    { offered: false },
  );
  await assert.rejects(
    lookupWithingsFirmware(
      identity,
      poster({ syp: { blc: "https://cdnfw.withings.net/firmware.bin" } }),
    ),
    /incomplete/,
  );
  await assert.rejects(
    lookupWithingsFirmware({ ...identity, modelCode: "BAD" }, poster({})),
    /Invalid scale identity/,
  );
});
