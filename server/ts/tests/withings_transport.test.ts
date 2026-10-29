import test from "node:test";
import assert from "node:assert/strict";
import { withingsPost, WITHINGS_ORIGIN } from "../withings_capture.ts";
import { captureWithingsSession } from "../withings_protocol.ts";
test("shared migration uses public HTTPS and rejects redirects and errors", async () => {
  let calls = 0;
  const result = await withingsPost(
    "v2/summary",
    "action=getforscale",
    async (url, init) => {
      calls++;
      assert.equal(new URL(String(url)).origin, "https://scalews.withings.net");
      assert.equal(WITHINGS_ORIGIN, new URL(String(url)).origin);
      assert.equal(init?.redirect, "error");
      assert.equal(init?.method, "POST");
      assert.equal("dispatcher" in (init ?? {}), false);
      return Response.json({ status: 0, body: [] });
    },
  );
  assert.deepEqual(result.body, []);
  assert.equal(calls, 1);
  await assert.rejects(
    withingsPost("../wrong", "", async () => {
      throw new Error("must not call");
    }),
    /Unsupported/,
  );
  await assert.rejects(
    withingsPost(
      "once",
      "",
      async () => new Response("redirect", { status: 302 }),
    ),
    /HTTP 302/,
  );
  await assert.rejects(
    withingsPost("once", "", async () =>
      Response.json({ status: 1, body: {} }),
    ),
    /unsuccessful/,
  );
});
test("optional display failure retains the independently valid roster", async () => {
  const capture = JSON.parse(
    await captureWithingsSession(
      { mac: "020000000001", secret: "test-only" },
      async (path) => {
        if (path === "once") return { body: { once: "synthetic-challenge" } };
        if (path === "session")
          return {
            body: {
              sessionid: "synthetic-session",
              ctp: { goff: 0, dst: 0, ngoff: 0 },
              ind: {},
              sp: { users: [{ id: 101 }] },
            },
          };
        if (path === "v2/screen") throw new Error("temporary outage");
        return { status: 0, body: [] };
      },
    ),
  );
  assert.deepEqual(capture.sp.users, [{ id: 101 }]);
  assert.equal(capture.screen_response, null);
  assert.deepEqual(capture.summary_response.body, []);
  assert.equal(JSON.stringify(capture).includes("synthetic-session"), false);
});

test("firmware lookup transport sends the probed model and requested version", async () => {
  await withingsPost(
    "once",
    "action=get",
    async (url) => {
      const query = new URL(String(url));
      assert.equal(query.searchParams.get("appname"), "WBS08");
      assert.equal(query.searchParams.get("appliver"), "1179");
      return Response.json({ status: 0, body: { once: "test" } });
    },
    { appName: "WBS08", currentFirmware: 1179 },
  );
});
