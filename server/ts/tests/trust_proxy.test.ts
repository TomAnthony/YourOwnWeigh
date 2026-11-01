import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer, request, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LocalSqlite } from "../sqlite.ts";
import type { AppEnv } from "../app.ts";
import { localListener, peerAddress } from "../local.ts";
import { forwardedScheme } from "../proxy.ts";

// Hash of "admin-password-123", as in app.test.ts.
const HASH =
  "pbkdf2_sha256$600000$000102030405060708090a0b0c0d0e0f$" +
  "5e470be3aac01b9df58840e2db41d217a2e240bc493fcb1aa0f4bbdc30c660f7";

test("peer address trusts X-Forwarded-For only when YOW_TRUST_PROXY is set", () => {
  // Without trust, the proxy's own address stays the key.
  assert.equal(peerAddress("127.0.0.1", "203.0.113.7", false), "127.0.0.1");
  assert.equal(
    peerAddress("198.51.100.4", "203.0.113.7", false),
    "198.51.100.4",
  );
  // With trust, the forwarded last hop is used when the immediate peer is
  // loopback or private — a containerised proxy reaches Node from a Docker
  // bridge IP (172.16/12), not loopback.
  assert.equal(peerAddress("127.0.0.1", "203.0.113.7", true), "203.0.113.7");
  assert.equal(
    peerAddress("::ffff:127.0.0.1", "2001:db8::1", true),
    "2001:db8::1",
  );
  assert.equal(peerAddress("172.18.0.1", "203.0.113.7", true), "203.0.113.7");
  assert.equal(peerAddress("10.1.2.3", "203.0.113.7", true), "203.0.113.7");
  assert.equal(peerAddress("fd00::1", "203.0.113.7", true), "203.0.113.7");
  // A direct public peer is never trusted, so it cannot spoof X-Forwarded-For.
  assert.equal(peerAddress("203.0.113.1", "10.0.0.5", true), "203.0.113.1");
  assert.equal(peerAddress("2001:db8::9", "10.0.0.5", true), "2001:db8::9");
  assert.equal(
    peerAddress("127.0.0.1", "1.1.1.1, 203.0.113.7", true),
    "203.0.113.7",
  );
  assert.equal(peerAddress("127.0.0.1", "not an address", true), "127.0.0.1");
  for (const malformed of [
    "999.999.999.999",
    "203.0.113.7:1234",
    "deadbeef",
    "1.2.3",
    "[2001:db8::1]",
  ])
    assert.equal(
      peerAddress("127.0.0.1", malformed, true),
      "127.0.0.1",
      malformed,
    );
  assert.equal(peerAddress("127.0.0.1", undefined, true), "127.0.0.1");
});

async function listen(
  trustProxy: boolean,
): Promise<{ server: Server; base: string; close: () => void }> {
  const directory = mkdtempSync(join(tmpdir(), "yow-proxy-test-"));
  const store = new LocalSqlite(join(directory, "proxy.sqlite3"));
  await store
    .asD1()
    .prepare("INSERT INTO settings(key,value) VALUES('admin_password',?)")
    .bind(HASH)
    .run();
  const env: AppEnv = { DB: store.asD1() };
  const hosts = new Set<string>();
  const server = createServer(
    localListener(env, false, hosts, false, trustProxy),
  );
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  hosts.add(`127.0.0.1:${port}`);
  return {
    server,
    base: `http://127.0.0.1:${port}`,
    close: () => {
      server.close();
      store.close();
      rmSync(directory, { recursive: true, force: true });
    },
  };
}

async function sync(
  base: string,
  ip: string,
  password: string,
): Promise<number> {
  const response = await fetch(`${base}/api/users/1/weights`, {
    headers: {
      "X-Forwarded-For": ip,
      Authorization: `Basic ${btoa(`reader:${password}`)}`,
    },
  });
  await response.arrayBuffer();
  return response.status;
}

test("behind a trusted proxy, a stranger's failed passwords do not lock out the household", async () => {
  const { base, close } = await listen(true);
  try {
    for (let i = 0; i < 20; i++)
      assert.equal(await sync(base, "203.0.113.66", "wrong-password"), 401);
    assert.equal(
      await sync(base, "203.0.113.66", "admin-password-123"),
      401,
      "stranger stays locked",
    );
    assert.notEqual(
      await sync(base, "198.51.100.10", "admin-password-123"),
      401,
      "household still syncs",
    );
  } finally {
    close();
  }
});

test("without YOW_TRUST_PROXY the proxy's own address is still the key (previous behaviour)", async () => {
  const { base, close } = await listen(false);
  try {
    for (let i = 0; i < 20; i++)
      await sync(base, "203.0.113.66", "wrong-password");
    assert.equal(await sync(base, "198.51.100.10", "admin-password-123"), 401);
  } finally {
    close();
  }
});

async function proxied(
  trustProxy: boolean,
): Promise<{ port: number; close: () => void }> {
  const directory = mkdtempSync(join(tmpdir(), "yow-proxy-scheme-"));
  const store = new LocalSqlite(join(directory, "scheme.sqlite3"));
  await store
    .asD1()
    .prepare("INSERT INTO settings(key,value) VALUES('admin_password',?)")
    .bind(HASH)
    .run();
  const env: AppEnv = { DB: store.asD1() };
  const hosts = new Set<string>(["waage.example.com"]);
  const server = createServer(
    localListener(env, false, hosts, false, trustProxy),
  );
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  return {
    port,
    close: () => {
      server.close();
      store.close();
      rmSync(directory, { recursive: true, force: true });
    },
  };
}

function head(
  port: number,
  headers: Record<string, string>,
): Promise<{ status: number; location?: string }> {
  return new Promise((resolve, reject) => {
    const req = request(
      { host: "127.0.0.1", port, path: "/", method: "GET", headers },
      (res) => {
        res.resume();
        resolve({
          status: res.statusCode ?? 0,
          location: res.headers.location,
        });
      },
    );
    req.on("error", reject);
    req.end();
  });
}

test("a trusted proxy's X-Forwarded-Proto=https avoids the redirect loop", async () => {
  const { port, close } = await proxied(true);
  try {
    const r = await head(port, {
      Host: "waage.example.com",
      "X-Forwarded-Proto": "https",
    });
    // Treated as https: the app proceeds (redirects an unauthenticated user to
    // /login) instead of 308-ing back to https and looping.
    assert.notEqual(r.status, 308);
    assert.ok(
      !/^https?:/i.test(r.location ?? ""),
      `unexpected absolute redirect: ${r.location}`,
    );
  } finally {
    close();
  }
});

test("without X-Forwarded-Proto a non-loopback plain-HTTP GET still upgrades to https", async () => {
  const { port, close } = await proxied(false);
  try {
    const r = await head(port, { Host: "waage.example.com" });
    assert.equal(r.status, 308);
    assert.ok((r.location ?? "").startsWith("https://"), r.location ?? "");
  } finally {
    close();
  }
});

test("forwardedScheme honours a trusted proxy and clamps malformed values", () => {
  // native TLS is always https
  assert.equal(forwardedScheme(true, false, undefined), "https");
  // no trusted proxy: plain http
  assert.equal(forwardedScheme(false, false, "https"), "http");
  // trusted proxy: explicit http stays http, anything else -> https
  assert.equal(forwardedScheme(false, true, "http"), "http");
  assert.equal(forwardedScheme(false, true, "https"), "https");
  assert.equal(forwardedScheme(false, true, "https,http"), "https");
  assert.equal(forwardedScheme(false, true, ["https", "http"]), "https");
  // missing or malformed header defaults to https and never throws downstream
  for (const bad of [undefined, "", "/", "ht!tp", "javascript:"])
    assert.equal(
      forwardedScheme(false, true, bad as any),
      "https",
      String(bad),
    );
});

test("a malformed X-Forwarded-Proto does not crash the listener", async () => {
  const { port, close } = await proxied(true);
  try {
    const r = await head(port, {
      Host: "waage.example.com",
      "X-Forwarded-Proto": "/",
    });
    // treated as https (clamped), so no 308 loop and no unhandled URL throw
    assert.notEqual(r.status, 308);
    assert.ok(r.status < 500, `status ${r.status}`);
  } finally {
    close();
  }
});
