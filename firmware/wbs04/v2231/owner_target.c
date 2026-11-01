/*
 * WBS04 (Body Cardio) v2231 owner-target Thumb injection source.
 *
 * NOT a complete firmware image. Ported from the WBS06 v1181 owner_target.c.
 * Addresses are pinned to the stock v2231 dump (see constants.py). The HTTP-only
 * build has been emulated and run on a Body Cardio; the HTTPS path is unfinished.
 *
 * Key WBS04 deviation vs WBS06: the WPP reply struct is larger. The length
 * field lives at offset 0xc0 (WBS06: 0x80), so the reply buffer is 0xc4 bytes
 * and the final length store targets reply+0xc0. TLV field offsets (reply[5..])
 * are WPP-protocol fixed and unchanged.
 */
#include <stdint.h>

enum { OWNER_ITEM = 0x1f0, STAGE_ITEM = 0x1f1, HOST_ITEM = 2, HOST_MAX = 63 };
enum { OWNER_MAGIC = 0x31535946 }; /* 'F','Y','S','1' */
enum { STAGE_MAGIC = 0x31475453 }; /* 'S','T','G','1' */
enum { REPLY_LEN_OFFSET = 0xc0, REPLY_BUF_SIZE = 0xc4 }; /* WBS04: was 0x80/0x84 */
#ifdef OWNER_HTTP_ONLY
enum { MAX_TRANSPORT = 0, DEFAULT_TRANSPORT = 0 };
#else
enum { MAX_TRANSPORT = 1, DEFAULT_TRANSPORT = 1 };
#endif

typedef int (*db_get_t)(uint16_t, void *, uint16_t);
typedef int (*db_set_t)(uint16_t, const void *, uint16_t);
typedef int (*setup_state_t)(void);
typedef void (*reply_init_t)(void *);
typedef void *(*wpp_context_t)(void);
typedef int (*wpp_reply_t)(void *, uint16_t, void *, uint32_t);

/* WBS04 stock helper addresses (thumb, see analysis/FINDINGS.md). */
#define DB_GET ((db_get_t)0x2e33d)
#define DB_SET ((db_set_t)0x2e2ad)
#define SETUP_STATE ((setup_state_t)0x1b171)
#define REPLY_INIT ((reply_init_t)0x68bad)
#define WPP_CONTEXT ((wpp_context_t)0x47fd9)
#define WPP_REPLY ((wpp_reply_t)0x46f25)

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
    if (len >= 12 && p[len - 12] == 'w' && p[len - 11] == 'i' &&
        p[len - 10] == 't' && p[len - 9] == 'h' && p[len - 8] == 'i' &&
        p[len - 7] == 'n' && p[len - 6] == 'g' && p[len - 5] == 's' &&
        p[len - 4] == '.' && p[len - 3] == 'n' && p[len - 2] == 'e' &&
        p[len - 1] == 't' && (len == 12 || p[len - 13] == '.')) return 0;
    return 1;
}

static __attribute__((always_inline)) inline int load_owner(char *host, uint8_t *mode,
                                                              uint8_t *length) {
    owner_record_t record;
    char current[64];
    clear_bytes(&record, sizeof(record));
    clear_bytes(current, sizeof(current));
    if (DB_GET(OWNER_ITEM, &record, sizeof(record)) != 0 ||
        DB_GET(HOST_ITEM, current, sizeof(current)) != 0 ||
        record.magic != OWNER_MAGIC || record.transport > MAX_TRANSPORT ||
        !hostname_valid(record.host, record.host_len) ||
        record.host[record.host_len] != 0) return 0;
    for (uint32_t i = 0; i < record.host_len; i++) {
        if (current[i] != record.host[i]) return 0;
    }
    if (current[record.host_len] != 0) return 0;
    for (uint32_t i = 0; i < record.host_len; i++) host[i] = record.host[i];
    host[record.host_len] = 0;
    *mode = record.transport;
    *length = record.host_len;
    return 1;
}

__attribute__((section(".text.owner"), used, noinline))
int owner_url_target(char *destination) {
    uint8_t mode = DEFAULT_TRANSPORT, length = 0;
    destination[0] = 0;
    if (!load_owner(destination, &mode, &length)) return 2;
    return mode;
}

#ifndef OWNER_HTTP_ONLY
/* Replaces the x509 CA-chain verify call (WBS04 0x2ba0c). Accepts only a parsed
 * Ed25519 leaf with non-null key context so the unchanged CertificateVerify
 * still proves possession of the leaf key. Removes server identity auth.
 * NOTE: leaf+0xbc / leaf+0xc0 are mbedtls struct offsets taken from WBS06; they
 * MUST be re-checked against the WBS04 mbedtls build in emulation before use. */
__attribute__((section(".text.owner"), used, noinline))
int owner_tls_accept_ed25519_leaf(const uint8_t *leaf) {
    const uint8_t *pk_info = *(const uint8_t * const *)(leaf + 0xbc);
    const void *pk_context = *(const void * const *)(leaf + 0xc0);
    if (pk_info && pk_context && pk_info[0] == 7) return 0;
    return 0x2a;
}
#endif

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
    if (DB_SET(HOST_ITEM, record.host, requested_length + 1) != 0 ||
        DB_SET(OWNER_ITEM, &record, sizeof(record)) != 0) return 3;
    return load_owner(readback, mode, host_length) ? 0 : 3;
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
            status = load_owner(host, &mode, &host_length) ? 0 : 2;
            if (status == 0) response_count = host_length;
        } else if (operation == 1 && length >= 8 && SETUP_STATE() == 0) {
            uint8_t requested_mode = payload[6];
            uint8_t requested_length = payload[7];
            if (requested_mode <= MAX_TRANSPORT && requested_length <= HOST_MAX &&
                length == (uint32_t)requested_length + 8)
                status = commit_owner((const char *)&payload[8], requested_mode,
                                      requested_length, host, &mode, &host_length);
            if (status == 0) response_count = host_length;
        } else if (operation >= 1 && operation <= 4 && SETUP_STATE() != 0) {
            status = 4;
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
                if (status == 0) host_length = 0;
            }
        } else if (operation == 5 && length == 7) {
            slice_offset = payload[6];
            status = load_owner(host, &mode, &host_length) ? 0 : 2;
            if (status == 0) {
                if (slice_offset >= host_length) status = 1;
                else {
                    response_count = host_length - slice_offset;
                    if (response_count > 6) response_count = 6;
                }
            }
        }
    }

    uint8_t reply[REPLY_BUF_SIZE] __attribute__((aligned(4)));
    REPLY_INIT(reply);
    reply[5] = 1; reply[6] = 0x70; /* TLV type 0x170, big endian */
    reply[7] = 0; reply[8] = 5 + response_count;
    reply[9] = 1; reply[10] = operation; reply[11] = status;
    reply[12] = mode; reply[13] = host_length;
    for (uint32_t i = 0; i < response_count; i++)
        reply[14 + i] = (uint8_t)host[slice_offset + i];
    *(uint16_t *)(reply + REPLY_LEN_OFFSET) = (uint16_t)(14 + response_count);
    WPP_REPLY(WPP_CONTEXT(), 0x170, reply, 0);
}
