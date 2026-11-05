/* WS-50 (wbs02) v1721-only owner HTTP patch, linked at 0x79558.
 *
 * The owner hostname lives in current-bank DBLIB item 2, as on the WS-30.
 * Hooks replace the WPP fallback call at 0x1e746, the setup DNS item-2
 * getter at 0x1eeec and the HTTP URL host copy at 0x26cd8.
 * Reply helpers and database entry points below apply only to stock v1721.
 */
#include <stdint.h>

typedef struct {
    uint16_t item;
    uint16_t capacity;
    int32_t cursor;
    uint16_t value_length;
    uint16_t found;
} db_query_t;
typedef int (*db_query_open_t)(db_query_t *, uint16_t, uint16_t);
typedef int (*db_query_read_t)(db_query_t *, void *);
typedef int (*db_query_close_t)(db_query_t *);
typedef int (*db_set_t)(uint16_t, const void *, uint16_t);

typedef int (*frag_send_t)(void *, const void *, uint32_t);
typedef void (*reset_tx_t)(void *);
typedef int (*fallback_t)(void *, uint16_t, const uint8_t *, uint32_t);

/* Query reads use the current-bank pointer at 0x1fff1988; the stock
 * item getter at 0x2a929 reads the default-bank context instead. */
#define DB_QUERY_OPEN ((db_query_open_t)0x2a1a1)
#define DB_QUERY_READ ((db_query_read_t)0x2a235)
#define DB_QUERY_CLOSE ((db_query_close_t)0x2a20d)
#define DB_SET ((db_set_t)0x2a509)
#define FRAG_SEND ((frag_send_t)0x55b47)
#define RESET_TX ((reset_tx_t)0x1e121)
#define STOCK_FALLBACK ((fallback_t)0x1efa5)

static __attribute__((always_inline)) inline int valid_host(const uint8_t *s, uint32_t n) {
    if (n < 1 || n > 59) return 0;
    for (uint32_t i = 0; i < n; ++i) {
        uint8_t c = s[i];
        int ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                 (c >= '0' && c <= '9') || c == '-' || c == '.';
        if (!ok) return 0;
    }
    return 1;
}

static __attribute__((always_inline)) inline uint8_t load_host(char *dst) {
    for (uint32_t i = 0; i < 64; ++i) dst[i] = 0;
    db_query_t query;
    if (DB_QUERY_OPEN(&query, 2, 64) != 0) return 0;
    int result = DB_QUERY_READ(&query, dst);
    int close_result = DB_QUERY_CLOSE(&query);
    if (result != 0 || close_result != 0) { dst[0] = 0; return 0; }
    uint8_t n = 0;
    while (n < 60 && dst[n]) ++n;
    if (!valid_host((const uint8_t *)dst, n) || dst[n] != 0) {
        dst[0] = 0;
        return 0;
    }
    return n;
}

__attribute__((section(".text.owner"), used, noinline))
int owner_target_read(uint16_t item, char *dst, uint16_t capacity) {
    if (item != 2 || capacity != 64) return 1;
    return load_host(dst) ? 0 : 1;
}

__attribute__((section(".text.owner"), used, noinline))
char *owner_url_target_copy(char *dst, const char *unused_source) {
    (void)unused_source;
    load_host(dst);
    return dst;
}

static __attribute__((always_inline)) inline void owner_send_reply(
    void *context, uint8_t op, uint8_t requested_status) {
    char host[64];
    uint8_t host_len = requested_status == 0 ? load_host(host) : 0;
    uint8_t status = requested_status;
    if (status == 0 && host_len == 0) status = op == 0 ? 2 : 3;
    uint8_t frame[80];
    uint32_t value_len = 4 + (status == 0 ? host_len : 0);
    uint32_t payload_len = value_len + 4;
    frame[0] = 1;
    frame[1] = 1; frame[2] = 0x70;
    frame[3] = 0; frame[4] = (uint8_t)payload_len;
    frame[5] = 1; frame[6] = 0x70;
    frame[7] = 0; frame[8] = (uint8_t)value_len;
    frame[9] = 1; frame[10] = op; frame[11] = status;
    frame[12] = status == 0 ? host_len : 0;
    for (uint32_t i = 0; i < host_len && status == 0; ++i)
        frame[13 + i] = (uint8_t)host[i];
    RESET_TX(context);
    FRAG_SEND((uint8_t *)context + 0x200, frame, 13 + (status == 0 ? host_len : 0));
}

__attribute__((section(".text.owner"), used, noinline))
void owner_reply_read(void *context) { owner_send_reply(context, 0, 0); }

__attribute__((section(".text.owner"), used, noinline))
void owner_reply_write(void *context) { owner_send_reply(context, 1, 0); }

__attribute__((section(".text.owner"), used, noinline))
void owner_reply_write_failed(void *context) { owner_send_reply(context, 1, 3); }

__attribute__((section(".text.owner"), used, noinline))
int owner_wpp_dispatch(void *context, uint16_t command,
                       const uint8_t *arg, uint32_t length) {
    if (command != 0x170) return STOCK_FALLBACK(context, command, arg, length);
    if (!arg || length < 7 || arg[0] != 1 || arg[1] != 0x70 ||
        arg[2] != 0 || (uint32_t)arg[3] + 4 != length || arg[4] != 1)
        return -1;
    uint32_t callback;
    if (arg[5] == 0 && length == 7 && arg[6] == 0) {
        __asm__ volatile ("ldr %0, =0xA1B2C3D4" : "=r"(callback));
    } else if (arg[5] == 1 && length >= 8 &&
               (uint32_t)arg[6] + 7 == length &&
               valid_host(arg + 7, arg[6])) {
        char host[64];
        uint8_t requested = arg[6];
        for (uint32_t i = 0; i < requested; ++i) host[i] = (char)arg[7 + i];
        host[requested] = 0;
        int saved = DB_SET(2, host, (uint16_t)(requested + 1)) == 0;
        if (saved) {
            uint8_t read_len = load_host(host);
            saved = read_len == requested;
            for (uint32_t i = 0; saved && i < requested; ++i)
                if ((uint8_t)host[i] != arg[7 + i]) saved = 0;
        }
        if (saved)
            __asm__ volatile ("ldr %0, =0xA1B2C3D5" : "=r"(callback));
        else
            __asm__ volatile ("ldr %0, =0xA1B2C3D6" : "=r"(callback));
    } else {
        return -1;
    }
    *(volatile uint32_t *)((uint8_t *)context + 0x198) = callback;
    return 0;
}
