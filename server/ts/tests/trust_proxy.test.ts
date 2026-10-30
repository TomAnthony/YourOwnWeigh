import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LocalSqlite } from "../sqlite.ts";
import type { AppEnv } from "../app.ts";
import { localListener, peerAddress } from "../local.ts";

// Hash of "admin-password-123", as in app.test.ts.
const HASH =
  "pbkdf2_sha256$600000$000102030405060708090a0b0c0d0e0f$" +
  "5e470be3aac01b9df58840e2db41d217a2e240bc493fcb1aa0f4bbdc30c660f7";

test("peer address only trusts X-Forwarded-For from a loopback proxy when enabled", () => {
  assert.equal(peerAddress("127.0.0.1", "203.0.113.7", false), "127.0.0.1");
  assert.equal(peerAddress("127.0.0.1", "203.0.113.7", true), "203.0.113.7");
  assert.equal(
    peerAddress("::ffff:127.0.0.1", "2001:db8::1", true),
    "2001:db8::1",
  );
  assert.equal(
    peerAddress("198.51.100.4", "203.0.113.7", true),
    "198.51.100.4",
  );
  assert.equal(
    peerAddress("127.0.0.1", "1.1.1.1, 203.0.113.7", true),
    "203.0.113.7",
  );
  assert.equal(peerAddress("127.0.0.1", "not an address", true), "127.0.0.1");
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
