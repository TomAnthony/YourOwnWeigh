# Cloudflare Deployment

The Worker serves the same TypeScript application as Node. D1 stores household data; one SQLite-backed Durable Object brokers the outbound Python WebSocket. There is no Python service or firmware compiler in Cloudflare.

## Guided Deployment

```sh
npm ci
npx wrangler login
npm run setup:cloudflare -- --name YOUR-SHORT-WORKER-NAME --deploy
```

The wrapper uses the pinned Wrangler in this repository. It finds or creates `<name>-data`, saves its ID, applies D1 migrations, packages the static signed Shortcut, and deploys with `YOW_BOOTSTRAP_TOKEN` supplied through Wrangler's `--secrets-file`. The secret never enters tracked configuration. Keep the printed token private. Open Wrangler's HTTPS URL, enter the token, and immediately set the admin password. Once initialized, the token cannot sign in.

Deployment state is in ignored `local/deployment/<name>/`. Rerun the same command after interruptions or for updates. It reuses that D1 database and token; it does not delete or recreate data. Back up through Settings before updating an existing household. A differently named deployment is a separate installation. If login or deployment fails, resolve the Wrangler error and rerun; do not create a second database to work around it.

The full hostname must fit **48 ASCII bytes for WBS06 / 59 for WS-30**. A long account subdomain may require a custom domain even with a short Worker name. WS-30 calls HTTP port 80: do not install an edge-level redirect, Access login or challenge in front of the scale endpoints. The app accepts HTTP only on scale routes and requires HTTPS for administration, Sync and bridge traffic.

## Manual Configuration

Copy `wrangler.jsonc.example` to ignored `wrangler.jsonc`. Supply your database ID and Worker name, retaining `YOW_BRIDGE`, its `BridgeDurableObject` class and `bridge-v1` migration.

```sh
npm run assets:prepare
npx wrangler d1 migrations apply DB --remote --config wrangler.jsonc
npx wrangler secret put YOW_BOOTSTRAP_TOKEN --config wrangler.jsonc
npx wrangler deploy --config wrangler.jsonc
```

Set the bootstrap secret **before a first public deployment**. Public setup refuses to initialize without it. The wrapper handles secrets on the initial deploy, avoiding a public unprotected setup interval. Current Wrangler supports both [Durable Object migration styles](https://developers.cloudflare.com/durable-objects/reference/durable-objects-migrations/); this repository retains the supported `migrations` form.

## Local Worker Check (No Cloud Changes)

```sh
npm run setup:cloudflare -- --name yow-test --dry-run
npx wrangler d1 migrations apply DB --local --config local/deployment/yow-test-dry-run/wrangler.json
npx wrangler dev --local --config local/deployment/yow-test-dry-run/wrangler.json \
  --var YOW_BOOTSTRAP_TOKEN:use-a-long-disposable-test-token
```

This creates no remote database or deployment. Use only synthetic identities and the bridge's `--simulate` mode. `tools/check_bridge_integration.mjs` verifies real WebSocket pairing/routing against either local runtime; see its header and [contributor checks](../../CONTRIBUTING.md). Never run seed SQL or dummy-device tests against personal data.
