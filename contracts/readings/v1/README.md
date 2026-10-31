# Readings API

Use HTTP Basic authentication with username `reader` and the household Sync API
password. A user reference is a numeric ID or an unambiguous three-letter name.

```sh
curl --user reader 'https://YOUR_SERVER/api/users/ALX/readings?since=2026-01-01&limit=100'
```

`GET /api/users/USER/readings` returns every stored measurement group for that
user, newest first. A weigh-in can produce several groups with the same time:
WBS13 sends weight/body composition and a separate heart-rate-only group.
Do not assume every group contains weight or treat a missing value as zero.

The response contains `user`, `readings`, `available_metrics`, and `next_cursor`.
Each reading includes:

- `id`, `scale`, `meastime`, `timestamp`, `time_quality`, `received_at`,
  `ordering_time`, `attribution`, `candidate_ids` and `health_sync_acknowledged_at`.
- `weight_kg` (decimal string), `value` (integer) and `unit` (decimal exponent),
  all `null` for a group without weight.
- `metrics`: named decimal strings for documented whole-body metrics. Keys are
  `weight_kg`, `fat_mass_kg`, `fat_ratio_pct`, `fat_free_mass_kg`, `muscle_mass_kg`,
  `water_mass_kg`, `bone_mass_kg`, `heart_rate_bpm`, `visceral_fat_index`,
  `basal_metabolic_rate_kcal` (kcal/day) and `metabolic_age_years`. Only values
  actually received are included. No body-fat percentage is inferred from mass.
- `measures`: the original integer `type`, `value`, `unit`, and any additional
  fields such as `position`. Physical value is `value × 10^unit`. Unknown type IDs
  are retained here without guessed labels. If several positions share a type,
  they remain separate raw entries rather than an arbitrary named whole-body value.
- `group`: the complete measurement group, including `algo` and unknown fields.
  Older stored rows without this metadata expose their timestamp and measures.

`available_metrics` lists documented types received anywhere in this user's
history, plus Weight as the default. Each entry has `type`, `key`, `label`, `unit`.
The dashboard and readings views use the same list for their Measurement selector;
each selection fetches the latest matching groups, rather than hiding older
heart-rate results behind newer weight-only uploads.

`since` is an inclusive UTC date (`YYYY-MM-DD`); `limit` is 1–1000 (default 100).
Pass `next_cursor` back as `cursor` with the same filters until it is `null`.
The cursor includes ordering time and row ID, so equal-time groups are not skipped.
Untrusted device dates use receive time for ordering and have `timestamp:null`.
The older exclusive `before` epoch filter is also accepted; prefer the cursor.

`GET /api/users/USER/weights` retains the existing weight-only response and excludes
groups without weight. The Apple Health `health-sync/next` and `health-sync/ack`
endpoints also remain weight-only. Their receipt confirms a weight import, not
that body composition or heart rate was imported. Reading the general API does
not acknowledge or remove anything.

All endpoints use the same household credential. They do not provide separate
per-user authorization. No device secrets or session credentials appear in these
responses. Source metric IDs follow the [Withings API](https://developerbeta.withings.com/api-reference/).
