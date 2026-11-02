import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { once } from "node:events";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { localListener } from "../local.ts";
import { LocalSqlite } from "../sqlite.ts";

test("scale-only HTTP listener ingests WS50 CGI uploads without exposing application routes", async () => {
  const directory = mkdtempSync(join(tmpdir(), "yow-local-cgi-"));
  const store = new LocalSqlite(join(directory, "test.sqlite3"));
  const db = store.asD1();
  const hosts = new Set<string>();
  const server = createServer(
    localListener({ DB: db, ALLOW_HTTP_SCALE: true }, false, hosts, true),
  );
  try {
    const mac = "02:00:00:00:00:50", secret = "0123456789abcdef";
    await db.prepare(
      "INSERT INTO scales(id,label,model,mac,secret) VALUES(1,'Test WS50','WS50','020000000050',?)",
    ).bind(secret).run();
    const listening = once(server, "listening");
    server.listen(0, "127.0.0.1");
    await listening;
    const address = server.address();
    assert.ok(address && typeof address !== "string");
    const authority = `127.0.0.1:${address.port}`;
    hosts.add(authority);
    const base = `http://${authority}`;
    const post = (path: string, fields: Record<string, string>) => fetch(base + path, {
      method: "POST", body: new URLSearchParams(fields),
    });
    const challenge = await post("/cgi-bin/once", { action: "get" });
    assert.equal(challenge.status, 200);
    const challengeResult: unknown = await challenge.json();
    assert.ok(challengeResult && typeof challengeResult === "object" && "body" in challengeResult);
    const challengeBody = challengeResult.body;
    assert.ok(challengeBody && typeof challengeBody === "object" && "once" in challengeBody);
    const nonce = challengeBody.once;
    assert.ok(typeof nonce === "string");
    // Sanitized native WS50 request shape from an owner packet capture:
    // root /session, MD5, no query parameters or hash-method marker.
    const sessionFields = {
      action: "new", auth: mac, currentfw: "1023", mfgid: "0",
      batterylvl: "64", duration: "300", zreboot: "1", trigger: "weather", enrich: "t",
      hash: createHash("md5").update(`${mac}:${secret}:${nonce}`).digest("hex"),
    };
    const wrongHash = (sessionFields.hash[0] === "0" ? "1" : "0") + sessionFields.hash.slice(1);
    const invalid = await post("/session", { ...sessionFields, hash: wrongHash });
    assert.equal(invalid.status, 403);
    await invalid.arrayBuffer();
    const opened = await post("/session", sessionFields);
    assert.equal(opened.status, 200);
    const openedResult: unknown = await opened.json();
    assert.ok(openedResult && typeof openedResult === "object" && "body" in openedResult);
    const openedBody = openedResult.body;
    assert.ok(openedBody && typeof openedBody === "object" && "sessionid" in openedBody);
    const session = openedBody.sessionid;
    assert.ok(typeof session === "string");
    const replay = await post("/cgi-bin/session", sessionFields);
    assert.equal(replay.status, 403);
    await replay.arrayBuffer();
    const timestamp = Math.floor(Date.now() / 1000);
    const measures = [
      { type: 1, value: 72350, unit: -3 },
      { type: 11, value: 64, unit: 0 },
    ];
    const uploaded = await post("/cgi-bin/measure", {
      action: "batchstore", sessionid: session, macaddress: mac,
      devtype: "1", category: "1", attribstatus: "0",
      measuregrps: JSON.stringify({ measuregrps: [{ meastime: timestamp, measures }] }),
    });
    assert.equal(uploaded.status, 200);
    assert.partialDeepStrictEqual(await uploaded.json(), {
      status: 0, body: [{ measuregrps: [] }],
    });
    const reading = await db.prepare(
      "SELECT scale_id,meastime,weight_value,weight_unit,measures_json FROM readings",
    ).first<{
      scale_id: number; meastime: number; weight_value: number;
      weight_unit: number; measures_json: string;
    }>();
    assert.deepEqual({ ...reading }, {
      scale_id: 1, meastime: timestamp, weight_value: 72350, weight_unit: -3,
      measures_json: JSON.stringify(measures),
    });
    const closed = await post("/cgi-bin/session", { action: "delete", sessionid: session });
    assert.equal(closed.status, 200);
    await closed.arrayBuffer();
    const rejected = await post("/cgi-bin/measure", {
      action: "batchstore", sessionid: session, macaddress: mac,
      devtype: "1", category: "1", attribstatus: "0",
      measuregrps: JSON.stringify({ measuregrps: [{ meastime: timestamp, measures }] }),
    });
    assert.equal(rejected.status, 403);
    await rejected.arrayBuffer();

    // Existing scale endpoints remain available, but CGI is not a blanket prefix.
    const legacy = await post("/once", { action: "get" });
    assert.equal(legacy.status, 200);
    await legacy.arrayBuffer();
    for (const [path, method] of [
      ["/cgi-bin/once", "GET"],
      ["/", "GET"],
      ["/api/backup/export", "GET"],
      ["/cgi-bin/api/backup/export", "GET"],
      ["/api/bridge/commands", "POST"],
      ["/setup", "POST"],
      ["/cgi-bin/setup", "POST"],
    ]) {
      const response = await fetch(base + path, { method });
      assert.equal(response.status, 404, `${method} ${path}`);
      await response.arrayBuffer();
    }
  } finally {
    if (server.listening) {
      const closed = once(server, "close");
      server.closeAllConnections();
      server.close();
      await closed;
    }
    store.close();
    rmSync(directory, { recursive: true, force: true });
  }
});
