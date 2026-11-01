/* WS-50 (wbs02) v1721-only owner HTTP patch, linked at 0x79558.
 *
 * Two hooks redirect the factory server target to the owner hostname stored
 * in the RAM buffer at 0x1fff081f (same role as the WS-30 DBLIB item 2):
 *   - 0x1e642: WPP dispatcher unknown-command fallthrough -> owner_wpp_dispatch
 *   - 0x26cd8: strcpy(dst, host) inside the URL host-copy helper ->
 *              owner_url_target_copy, which substitutes the owner host.
 * Reply path uses FRAG_SEND 0x55ac2 on ctx+0x200, matching the WS-30 build.
 */
#include <stdint.h>

/* RAM buffer holding the owner host (factory default: the wbs02-ws string). */
#define OWNER_HOST ((const char *)0x1fff081f)

typedef int (*frag_send_t)(void *, const void *, uint32_t);
typedef void (*reset_tx_t)(void *);
typedef int (*fallback_t)(void *, uint16_t, const uint8_t *, uint32_t);

#define FRAG_SEND ((frag_send_t)0x55ac2)
#define RESET_TX ((reset_tx_t)0x22eec)
/* Original unknown-command path at 0x1e734 (true VA of the fallback head). */
#define STOCK_FALLBACK ((fallback_t)0x1e734)

static __attribute__((always_inline)) inline int valid_host(const uint8_t *s, uint32_t n) {
    for (uint32_t i = 0; i < n; ++i) {
        uint8_t c = s[i];
        int ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                 (c >= '0' && c <= '9') || c == '-' || c == '.';
        if (!ok) return 0;
    }
    return 1;
}

static __attribute__((always_inline)) inline uint8_t load_host(char *dst) {
    const char *src = OWNER_HOST;
    uint8_t n = 0;
    while (src[n] && n < 63) { dst[n] = src[n]; ++n; }
    dst[n] = 0;
    return n;
}

__attribute__((section(".text.owner"), used, noinline))
char *owner_url_target_copy(char *dst, const char *unused_source) {
    /* The stock helper strcpy's the factory host global into dst; substitute
     * the owner buffer instead. Return dst like strcpy would. */
    (void)unused_source;
    char *p = dst;
    const char *src = OWNER_HOST;
    while ((*p++ = *src++) != 0) {}
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
        /* Persist the owner host into the RAM buffer the URL helper reads. */
        char *dst = (char *)OWNER_HOST;
        uint8_t requested = arg[6];
        for (uint32_t i = 0; i < requested; ++i) dst[i] = (char)arg[7 + i];
        dst[requested] = 0;
        char check[64];
        uint8_t read_len = load_host(check);
        int saved = read_len == requested;
        for (uint32_t i = 0; saved && i < requested; ++i)
            if ((uint8_t)check[i] != arg[7 + i]) saved = 0;
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
