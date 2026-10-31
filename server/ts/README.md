# Shared TypeScript Application

- `app.ts`: browser authentication, enrollment, user/readings/Sync routes, JSON APIs.
- `ui.ts`, `integrated_ui.ts`, `../static/`: server-rendered views and browser bridge controller.
- `scale_api.ts`, `ws30_md5.ts`: model-specific Wi-Fi authentication, settings, clock and idempotent readings ingestion.
- `metrics.ts`: documented metric names, exact decimal values, observed-metric selection and backup validation; unknown sensor fields stay raw.
- `withings_protocol.ts`, `withings_capture.ts`: one read-only migration exchange and public-HTTPS transport for both runtimes/models.
- `bridge.ts`: transport-independent pairing/routing. `bridge_node.ts` uses `ws`; `../cloudflare/bridge_do.ts` uses hibernating Worker WebSockets.
- `backup.ts`: explicit backup schema, validation/staging and transactional merge/replace.
- `sqlite.ts`: Node adapter implementing the used D1 subset, including atomic batches.
- `local.ts`: loopback application, optional native HTTPS and separate scale-only listener.

Run `npm run server:typecheck`, `npm run worker:typecheck` and `npm run server:test` from the root. Tests use temporary databases and synthetic credentials. Production Withings responses are represented by sanitized fixtures; tests do not contact the vendor or hardware.

Migrations are under `server/migrations/`, shared by SQLite/D1. Keep schema changes covered by transaction and backup tests.
