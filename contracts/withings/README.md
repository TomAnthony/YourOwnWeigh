# Withings Import Fixtures

These fixtures test importing existing users into YourOwnWeigh. They are not
responses to send directly to a scale.

## WS-30 Fixture

[`ws30-baseline.sanitized.json`](ws30-baseline.sanitized.json) preserves the response shape of a real WS-30 (WBS03) exchange through the shared [Node/Worker importer](../../server/ts/withings_capture.ts). The transport uses ordinary verified HTTPS to `scalews.withings.net`.

| Endpoint | Result |
| --- | --- |
| `/once` | Challenge received |
| `/session` | Session accepted; four users and device/time settings returned |
| `/v2/screen` | Successful response with four user entries and an empty device list |
| `/v2/summary` | Successful response with four user entries |

The importer retained its WBS06 query and `currentfw=1181`, with `mfgid=0` and
`feature_mask=0`. Those are upstream compatibility parameters, not observations
about this WS-30's running firmware. Authentication used the shared SHA-256
exchange; the owner server's separate WS-30 MD5 protocol was not changed. Weather
was not requested, so `weather_response: null` means uncaptured, not unsupported.

Vendor profile imports retain this shared SHA-256 compatibility exchange for
both WS-30 and WS-50; they do not select a vendor protocol from the model's
owner-server authentication. The speculative per-model vendor configuration
has been removed. WS-50 live acceptance remains unverified. See the
[evidence gate](../../docs/ws30-vendor-import-confirmation.md) before introducing
a model-specific exception.

## Preserved Details And Sanitization

The importer uses the `WBS06-Withings-readonly-baseline-v1` envelope for this shared endpoint. Determine the model from the enrolled device, not the envelope name.

Object keys, array lengths, scalar types, omitted fields and protocol constants
are preserved. In particular:

- `ind.fm` and `ind.ws` are zero; the weight and temperature codes are present.
- User `cs` strings are retained exactly (including empty values); `ft` arrays are empty. `ptf` and `bd` are absent.
- Some screen entries omit `deactivable_status`; others have `parent_screen_id`.
- Only some summary records contain `t36` or the `t1.o` field.

MAC, user/account IDs, names, sex, measurements, heights, ages, personal dates and
history values are synthetic. The transition timestamp and gravity value are
also replaced. User references remain consistent across roster, screen and
summary records. No device secret, session token or firmware offer is included.
History numbers test response shape, not graph rendering or measurement decoding.


## Verified Behavior

[The regression tests](../../server/ts/tests/ws30_withings_import.test.ts) replay
the shared exchange through the exported vendor transport wrapper, then exercise
the actual web importer against a temporary SQLite database. The WS-50 wrapper
case replays this same sanitized fixture to guard the compatibility contract;
it is not evidence of a successful live WS-50 exchange. The tests check:

1. Stage and preview the roster through the existing normalizer.
2. Import all four users and memberships, preserving their numeric IDs.
3. Leave scale settings/display state unchanged when importing users only.
4. Open a simulated WS-30 MD5 session with only `sessionid` and `syp.utc` in its
   response; keep `/v2/summary` empty.
5. Commit a synthetic reading against an imported user.

Run the offline regression from the repository root:

```sh
node --test server/ts/tests/ws30_withings_import.test.ts
```

For a developer-only check of a private baseline, set `YOW_WITHINGS_TEST_CAPTURE`
to its local JSON path. This still uses a temporary database and makes no network
requests. The tests use a synthetic device MAC/secret even with a private baseline.

## Enrollment Policy

Automatic enrollment applies WBS06 settings and required display responses only to
WBS06 records. WS-30 imports users but keeps the minimal WS-30 session.
Successful roster retrieval survives optional display failures. Both behaviors
are exercised by the integrated enrollment and transport tests.

WS-30 roster writes and richer historical graph support remain future model work.
