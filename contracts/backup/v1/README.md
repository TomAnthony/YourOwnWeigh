# Household Backup v1

`GET /api/backup/export` requires the signed-in administrator and returns a
`YOW-backup-v1` JSON document.
The structural envelope is in
`backup.schema.json`. Exact per-table columns and semantic validation are kept
in one place: [`server/ts/backup.ts`](../../../server/ts/backup.ts), with storage
constraints in [`server/migrations/`](../../../server/migrations/).

Household sections contain complete database rows. The three operational diagnostic
sections (`sync_audit`, `measure_attempts`, `measure_rejections`) are empty in
exports and ignored when importing older backups; they are not needed to restore
people, devices or readings. IDs are numeric, nullable columns remain `null`,
and JSON-valued database columns remain strings. Device secrets,
readings and optional password hashes are private backup contents. Browser
sessions, bridge invitations/pairings, active device sessions and nonces are
excluded. The raw `withings_capture` field is cleared; normalized
profiles are retained in `reviewed_captures`.

Measurement-only groups have `weight_value:null` and `weight_unit:null`.
`measures_json` preserves item metadata such as `position`; `group_json` preserves
the complete group, including `algo` and unknown fields. Pre-metric backups may
omit `group_json`; import supplies `null`. These JSON strings are validated before
staging, and richer readings and existing weight-only Health receipts survive
both merge and replace.

`POST /api/backup/import` accepts a multipart `backup` file plus `_csrf`, validates
at most 10 MiB / 25,000 household rows, and stages rows for 15 minutes. It renders a preview
containing `import_id` and a digest. `POST /api/backup/commit` requires these,
`_csrf`, `mode=merge|replace`, and `confirmed=1`, all from the same admin session.
`restore_access=1` explicitly restores included access settings and signs out
existing sessions. Otherwise current passwords remain.

Merge keeps local edits, matches users by numeric Withings ID and scales by MAC,
and remaps reading/scale references while deduplicating readings and receipts.
A matching MAC with a different model or secret is an error. Replace removes
household rows and restores the staged data. The final change is one SQLite
transaction or D1 batch; staging failures never replace active data. A committed
or expired preview cannot be reused.

Tests cover SQLite rollback, reference remapping, repeat merge and access
preservation. `tools/check_backup_integration.mjs` additionally exercises the
HTTP flow against a disposable Node or local Wrangler/D1 instance.
