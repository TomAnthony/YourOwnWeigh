# Web App And Scale Server

One TypeScript application runs on Node/SQLite or Cloudflare/D1. It serves Dashboard, Readings, Scales, Users, Sync and Settings; the device HTTP protocol; the generic readings API; and the bridge broker. Bluetooth and patching stay in Python.

## Local Quick Start

Node 24+ and `npm ci` are required. From the repository root:

```sh
npm run setup:local -- --scale-host YOUR_MAC_LAN_IP
```

The dashboard is `http://127.0.0.1:8080`. Setup creates a token under `local/data/bootstrap-token.txt` and prints it until the admin password exists. Enter it in the browser, then choose an eight-character-or-longer password. A separate Sync password is optional.

For scale traffic, install [Caddy](https://caddyserver.com/docs/install) and run the generated Caddyfile using the command setup prints. Only the Caddy process needs access to ports 80/443; Node and Python must not run as root. Stop foreground processes with Ctrl-C. The generated proxy sends only scale traffic to the separate listener, whose route allowlist excludes admin, bootstrap, Sync and bridge paths. No firewall or router changes are made by setup.

Caddy's [`tls internal`](https://caddyserver.com/docs/caddyfile/directives/tls) supplies the scale-facing certificate, with automatic trust-store installation disabled. The patched WBS06 does not authenticate that certificate. This does not make it trusted for iPhone or browser access. The local recipe deliberately uses loopback for administration; use a properly trusted HTTPS application endpoint for remote clients.

For dashboard-only development, `npm run server:start` needs no certificate or proxy. Use the main [README](../README.md) for enrollment, firmware and Wi-Fi setup.

## Environment

| Variable | Default / Purpose |
| --- | --- |
| `YOW_DB_PATH` | `local/data/yow.sqlite3`; auto-migrated SQLite |
| `YOW_PORT` / `YOW_LISTEN_HOST` | `8080` / `127.0.0.1` for the application |
| `YOW_BOOTSTRAP_TOKEN` | Optional explicit first-run token, at least 24 characters |
| `YOW_TLS_CERT` / `YOW_TLS_KEY` | Both PEM paths enable native HTTPS |
| `YOW_PUBLIC_ORIGIN` | External application origin if using native HTTPS under another hostname |
| `YOW_SCALE_PORT` | Optional separate HTTP scale-only listener; local setup uses `8081` |
| `YOW_SCALE_HOST` | `127.0.0.1`; proxy-facing bind address |
| `YOW_SCALE_PROXY_HOST` | `127.0.0.1:8081` for the setup recipe; exact allowed Host header |

Plain HTTP application listeners refuse non-loopback binds. A generic proxy must preserve the configured Host; do not expose the loopback application through an arbitrary HTTP tunnel. The bundled scale proxy is separate. Preserve the SQLite directory, bootstrap file and `bridge-pairing.json`; the latter contains only the server's pairing hashes, not device secrets.

## Import, Sync And Settings

Approved device enrollment stores the MAC/secret and Bluetooth observations, then fetches its profile using ordinary verified HTTPS at `scalews.withings.net`. Node and Worker use the **same** implementation, without pinning, OpenSSL or plaintext fallback. Settings apply automatically; only creating new local users needs selection. The same numeric ID means the same user, preserving local edits. Withings supplies approximate age rather than DOB; enter DOB when known.

WBS06 settings and display responses are required before its sync session can complete. If initial import fails, Finish Device Import retries. WS-30 does not adopt WBS06 display fixtures and keeps its minimal session. The server stores the profile; daily owner syncing does not call Withings. An optional read-only lookup for an unrecognised scale can use its Bluetooth MAC and secret to ask Withings for an advertised firmware URL and SHA-1. The browser receives only those offer fields, and the copyable issue report excludes credentials and users. This does not fetch or install the offered image.

Timezone arithmetic lives in TypeScript. The browser provides an IANA timezone; the server calculates UTC/current offset/next transition/next offset for both Wi-Fi responses and Bluetooth provisioning. Shared fixtures in `contracts/time/v1/` test boundary behavior and Python's wire encoding.

Scale settings delivery is reported as saved or sent, never device-confirmed. Imported WBS06 roster-member edits can be queued; people skipped during enrollment stay on the scale. New local-only profiles and WS-30 roster writes are not implemented. Captured screen/summary responses are currently replayed; weather is not a live forecast integration.

## Data And Backups

Use Settings → Export Database. The versioned JSON includes household users, devices and secrets, readings/raw values, memberships, settings, display baselines, audit rows and Apple Health receipts. Authentication sessions and bridge credentials are excluded. Treat exports as private.

Import uploads to bounded temporary staging (10 MiB / 25,000 rows), shows counts, then commits one SQLite transaction or D1 batch. Merge adds missing data, deduplicates readings and keeps existing user edits. Replace is explicit. Current passwords remain unless Restore Access Settings is selected; restoring them signs out sessions and revokes the bridge. Invalid rows or final-batch failures roll back. Staging expires after 15 minutes.

The Sync API uses HTTP Basic `reader:password`, sharing the admin password by default. It accepts a numeric user ID or unique three-letter name. See Sync in the app and [Apple Health](../connectors/Apple%20Health/README.md). Unknown users and errors return JSON. Readings API access covers all household users; the requested user is a filter, not an authorization boundary.

See [Cloudflare deployment](cloudflare/README.md) and [developer module map](ts/README.md).
