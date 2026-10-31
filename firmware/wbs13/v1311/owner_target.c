/* WBS13 stock v1311 owner-host injection for the first YOW candidate.
 *
 * All entry points are reached through existing WPP authorization/connection
 * checks. Configuration is held only in the current user bank; the factory
 * hostname, session secret, TLS keys and calibration remain unchanged.
 * Requires paired, qualified firmware hooks from patch_owner_target.py.
 */
#include <stdint.h>

enum { OWNER_ITEM = 0x1f0, STAGE_ITEM = 0x1f1, HOST_ITEM = 2, HOST_MAX = 48 };
enum { OWNER_MAGIC = 0x31574f59 }; /* bytes 'Y','O','W','1' */
enum { STAGE_MAGIC = 0x31475453 }; /* bytes 'S','T','G','1' */
enum { MAX_TRANSPORT = 1, DEFAULT_TRANSPORT = 1 };

typedef int (*db_get_t)(uint16_t, void *, uint16_t);
typedef int (*db_set_t)(uint16_t, const void *, uint16_t);
typedef int (*version_t)(void);
typedef void (*stock_host_t)(char *);
typedef void (*stock_offer_t)(const char *, const char *);
typedef void (*stock_log_t)(const char *);
typedef void (*reply_init_t)(void *);
typedef void *(*wpp_context_t)(void);
typedef int (*wpp_reply_t)(void *, uint16_t, void *, uint32_t);

#define DB_GET ((db_get_t)0x0807127f) /* current user bank */
#define DB_FACTORY_GET ((db_get_t)0x080298a1)
#define DB_SET ((db_set_t)0x080294c9)
#define VERSION_GET ((version_t)0x08016585)
#define STOCK_HOST ((stock_host_t)0x080459cd)
#define STOCK_OFFER ((stock_offer_t)0x08048049)
#define STOCK_LOG ((stock_log_t)0x08067b11)
#define REPLY_INIT ((reply_init_t)0x08074c4d)
#define WPP_CONTEXT ((wpp_context_t)0x08042335)
#define WPP_REPLY ((wpp_reply_t)0x08041271)

typedef struct {
    uint32_t magic;
    uint8_t transport;
    uint8_t host_len;
    char host[64];
} owner_record_t;

typedef struct {
    uint32_t magic;
    uint8_t transfer_id;
    uint8_t transport;
    uint8_t total_len;
    uint8_t next_offset;
    char host[64];
} stage_record_t;

static __attribute__((always_inline)) inline void clear_bytes(void *dst, uint32_t len) {
    volatile uint8_t *p = (volatile uint8_t *)dst;
    for (uint32_t i = 0; i < len; i++) p[i] = 0;
}

static __attribute__((always_inline)) inline int hostname_valid(const char *p, uint32_t len) {
    if (len == 0 || len > HOST_MAX) return 0;
    uint32_t label = 0;
    for (uint32_t i = 0; i < len; i++) {
        uint8_t c = (uint8_t)p[i];
        if (c == '.') {
            if (label == 0 || p[i - 1] == '-') return 0;
            label = 0;
            continue;
        }
        if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-')) return 0;
        if (label == 0 && c == '-') return 0;
        if (++label > 63) return 0;
    }
    if (label == 0 || p[len - 1] == '-') return 0;
    /* Avoid accidental return to the vendor domain. Last 12 bytes equal
     * "withings.net" for both the bare host and its subdomains. */
    if (len >= 12 && p[len - 12] == 'w' && p[len - 11] == 'i' &&
        p[len - 10] == 't' && p[len - 9] == 'h' && p[len - 8] == 'i' &&
        p[len - 7] == 'n' && p[len - 6] == 'g' && p[len - 5] == 's' &&
        p[len - 4] == '.' && p[len - 3] == 'n' && p[len - 2] == 'e' &&
        p[len - 1] == 't' && (len == 12 || p[len - 13] == '.')) return 0;
    return 1;
}

/* 0 = valid owner, 1 = absent (retain factory behavior), 2 = invalid/error.
 * This is a user-bank record; no factory host, identity or calibration writes.
 */
static __attribute__((always_inline)) inline int load_owner(char *host, uint8_t *mode,
                                                              uint8_t *length) {
    owner_record_t record;
    clear_bytes(&record, sizeof(record));
    int result = DB_GET(OWNER_ITEM, &record, sizeof(record));
    if (result == 3) return 1; /* DBLIB item not found */
    if (result != 0 || record.magic != OWNER_MAGIC ||
        record.transport > MAX_TRANSPORT ||
        !hostname_valid(record.host, record.host_len) ||
        record.host[record.host_len] != 0) return 2;
    for (uint32_t i = 0; i < record.host_len; i++) host[i] = record.host[i];
    host[record.host_len] = 0;
    *mode = record.transport;
    *length = record.host_len;
    return 0;
}

__attribute__((section(".text.owner"), used, noinline))
int owner_target_enabled(void) {
    char host[64];
    uint8_t mode = 1, length = 0;
    return load_owner(host, &mode, &length) == 0;
}

/* Never schedule a Wi-Fi firmware replacement from an owner-server reply.
 * Passing NULLs to the original routine also clears any earlier cached offer.
 * Stock behavior is retained only when the owner record is absent.
 */
__attribute__((section(".text.owner"), used, noinline))
void owner_firmware_offer(const char *url, const char *sha1) {
    char host[64];
    uint8_t mode = 1, length = 0;
    if (load_owner(host, &mode, &length) != 1) { url = 0; sha1 = 0; }
    STOCK_OFFER(url, sha1);
}

/* Session close is the sole caller of the stock Wi-Fi firmware downloader.
 * Clear any stale factory offer before its download/pending-offer branches,
 * including when a later owner-server session omitted an offer entirely.
 * The hook replaces a logging call and preserves that call's argument/ABI.
 */
__attribute__((section(".text.owner"), used, noinline))
void owner_sync_offer_gate(const char *message) {
    char host[64];
    uint8_t mode = 1, length = 0;
    STOCK_LOG(message);
    if (load_owner(host, &mode, &length) != 1) STOCK_OFFER(0, 0);
}

/* Replaces the host getter call in the common URL builder. The patched caller
 * uses r0 as its HTTP/HTTPS selector. Missing owner config retains the stock
 * factory host and HTTPS; invalid committed config leaves an empty host.
 */
__attribute__((section(".text.owner"), used, noinline))
int owner_url_target(char *destination) {
    uint8_t mode = DEFAULT_TRANSPORT, length = 0;
    destination[0] = 0;
    int state = load_owner(destination, &mode, &length);
    if (state == 1) { STOCK_HOST(destination); return 1; }
    return state == 0 ? mode : 2;
}

/* The Wi-Fi connection test resolves a separate 64-byte hostname before its
 * /once probe. It must use the same committed owner record as regular sync.
 */
__attribute__((section(".text.owner"), used, noinline))
int owner_dns_target(uint16_t item, char *destination, uint16_t capacity) {
    if (item != HOST_ITEM || capacity != 64) return 1;
    uint8_t mode = DEFAULT_TRANSPORT, length = 0;
    clear_bytes(destination, capacity);
    int state = load_owner(destination, &mode, &length);
    if (state == 1) return DB_FACTORY_GET(item, destination, capacity);
    return state == 0 ? 0 : 3;
}

/* Existing identity replies have a length-prefixed secret slot at +0x86.
 * Populate it without touching factory DBLIB or bypassing stock WPP access
 * checks. The wrapper returns the same version as the displaced getter call.
 */
__attribute__((section(".text.owner"), used, noinline))
int owner_identity_version(uint8_t *identity) {
    char secret[17];
    clear_bytes(secret, sizeof(secret));
    identity[0x86] = 0;
    int valid = DB_FACTORY_GET(3, secret, sizeof(secret)) == 0 && secret[16] == 0;
    for (uint32_t i = 0; i < 16 && valid; i++) {
        uint8_t c = (uint8_t)secret[i];
        valid = (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') ||
                (c >= 'A' && c <= 'F');
    }
    if (valid) {
        identity[0x86] = 16;
        for (uint32_t i = 0; i < 16; i++) identity[0x87 + i] = (uint8_t)secret[i];
    }
    clear_bytes(secret, sizeof(secret));
    return VERSION_GET();
}

static __attribute__((always_inline)) inline int commit_owner(const char *source,
                                                    uint8_t requested_mode,
                                                    uint8_t requested_length,
                                                    char *readback,
                                                    uint8_t *mode,
                                                    uint8_t *host_length) {
    if (requested_mode > MAX_TRANSPORT || !hostname_valid(source, requested_length)) return 1;
    owner_record_t record;
    clear_bytes(&record, sizeof(record));
    record.magic = OWNER_MAGIC;
    record.transport = requested_mode;
    record.host_len = requested_length;
    for (uint32_t i = 0; i < requested_length; i++) record.host[i] = source[i];
    /* One DBLIB transaction commits mode and hostname together. A failed
     * staged transfer leaves the previous committed target in place. */
    if (DB_SET(OWNER_ITEM, &record, sizeof(record)) != 0) return 3;
    return load_owner(readback, mode, host_length) == 0 ? 0 : 3;
}

__attribute__((section(".text.owner"), used, noinline))
void owner_wpp_170(const uint8_t *payload, uint32_t length) {
    char host[64];
    uint8_t mode = DEFAULT_TRANSPORT, host_length = 0, response_count = 0, slice_offset = 0;
    uint8_t operation = 0, status = 1;
    clear_bytes(host, sizeof(host));

    if (length >= 6 && payload[0] == 1 && payload[1] == 0x70 &&
        payload[2] == 0 && (uint32_t)payload[3] + 4 == length &&
        payload[4] == 1) {
        operation = payload[5];
        if (operation == 0 && length == 6) {
            status = load_owner(host, &mode, &host_length) == 0 ? 0 : 2;
            if (status == 0) response_count = host_length;
        } else if (operation == 1 && length >= 8) {
            uint8_t requested_mode = payload[6];
            uint8_t requested_length = payload[7];
            if (requested_mode <= MAX_TRANSPORT && requested_length <= HOST_MAX &&
                length == (uint32_t)requested_length + 8)
                status = commit_owner((const char *)&payload[8], requested_mode,
                                      requested_length, host, &mode, &host_length);
            if (status == 0) response_count = host_length;
        } else if (operation == 2 && length == 9) {
            stage_record_t stage;
            clear_bytes(&stage, sizeof(stage));
            stage.magic = STAGE_MAGIC;
            stage.transfer_id = payload[6];
            stage.transport = payload[7];
            stage.total_len = payload[8];
            if (stage.transport <= MAX_TRANSPORT && stage.total_len > 0 &&
                stage.total_len <= HOST_MAX) {
                status = DB_SET(STAGE_ITEM, &stage, sizeof(stage)) == 0 ? 0 : 3;
                if (status == 0) mode = stage.transport;
            }
        } else if (operation == 3 && length >= 10) {
            stage_record_t stage;
            clear_bytes(&stage, sizeof(stage));
            uint8_t chunk_len = payload[8];
            if (chunk_len > 0 && chunk_len <= 6 &&
                length == (uint32_t)chunk_len + 9 &&
                DB_GET(STAGE_ITEM, &stage, sizeof(stage)) == 0 &&
                stage.magic == STAGE_MAGIC &&
                stage.transfer_id == payload[6] &&
                stage.total_len > 0 && stage.total_len <= HOST_MAX &&
                stage.transport <= MAX_TRANSPORT && stage.next_offset == payload[7] &&
                (uint32_t)stage.next_offset + chunk_len <= stage.total_len) {
                for (uint32_t i = 0; i < chunk_len; i++)
                    stage.host[stage.next_offset + i] = (char)payload[9 + i];
                stage.next_offset += chunk_len;
                status = DB_SET(STAGE_ITEM, &stage, sizeof(stage)) == 0 ? 0 : 3;
                if (status == 0) mode = stage.transport;
            }
        } else if (operation == 4 && length == 7) {
            stage_record_t stage;
            clear_bytes(&stage, sizeof(stage));
            if (DB_GET(STAGE_ITEM, &stage, sizeof(stage)) == 0 &&
                stage.magic == STAGE_MAGIC &&
                stage.transfer_id == payload[6] && stage.transport <= MAX_TRANSPORT &&
                stage.total_len > 0 && stage.total_len <= HOST_MAX &&
                stage.next_offset == stage.total_len) {
                status = commit_owner(stage.host, stage.transport, stage.total_len,
                                      host, &mode, &host_length);
                if (status == 0) host_length = 0; /* progress reply fits ATT20 */
            }
        } else if (operation == 5 && length == 7) {
            slice_offset = payload[6];
            status = load_owner(host, &mode, &host_length) == 0 ? 0 : 2;
            if (status == 0) {
                if (slice_offset >= host_length) status = 1;
                else {
                    response_count = host_length - slice_offset;
                    if (response_count > 6) response_count = 6;
                }
            }
        }
    }

    uint8_t reply[0xc4] __attribute__((aligned(4)));
    REPLY_INIT(reply);
    reply[5] = 1; reply[6] = 0x70; /* TLV type 0x170, big endian */
    reply[7] = 0; reply[8] = 5 + response_count;
    reply[9] = 1; reply[10] = operation; reply[11] = status;
    reply[12] = mode; reply[13] = host_length;
    for (uint32_t i = 0; i < response_count; i++)
        reply[14 + i] = (uint8_t)host[slice_offset + i];
    *(uint16_t *)(reply + 0xc0) = (uint16_t)(14 + response_count);
    WPP_REPLY(WPP_CONTEXT(), 0x170, reply, 0);
}
