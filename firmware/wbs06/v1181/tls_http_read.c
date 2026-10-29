/* WBS06 v126 experimental TLS-to-HTTP receive staging.
 *
 * Addresses and the connection layout are pinned to the owner's v125 image.
 * The stock HTTP loop supplies a 512-byte area, but its TLS reader can return
 * a complete decrypted record larger than 512 bytes. This function preserves
 * the stock 512-byte *input* request while receiving output into a separate
 * buffer, passes every returned byte to the unchanged HTTP parser, then frees
 * the buffer before returning. It is called only from the HTTP receive loop.
 */
#include <stdint.h>

enum { INPUT_CHUNK = 0x200, STAGING_CAP = 0x1800 };

typedef void *(*malloc_t)(uint32_t);
typedef void (*free_t)(void *);
typedef int (*tls_read_t)(void *, uint32_t);
typedef void (*http_parse_t)(void *, void *, const void *, uint32_t);

#define FW_MALLOC ((malloc_t)0x4cadd)
#define FW_FREE ((free_t)0x4caed)
#define FW_TLS_READ ((tls_read_t)0x4a5fd)
#define FW_HTTP_PARSE ((http_parse_t)0x60b1)

__attribute__((section(".text.v126"), used, noinline))
int v126_http_read_parse(void *const *connection_slot) {
    uint8_t *scratch = (uint8_t *)FW_MALLOC(STAGING_CAP);
    if (!scratch) return -8;

    int count = FW_TLS_READ(scratch, INPUT_CHUNK);
    if (count >= 0) {
        /* The v125 encrypted-record bound is 4096 bytes. At most one partial
         * record can be buffered between reads; adding 512 input bytes can
         * produce less than 4608 plaintext bytes, within STAGING_CAP. */
        if ((uint32_t)count > STAGING_CAP || !*connection_slot) {
            count = -8;
        } else {
            uint8_t *connection = (uint8_t *)*connection_slot;
            FW_HTTP_PARSE(connection + 0x238, connection + 0x258,
                          scratch, (uint32_t)count);
        }
    }
    FW_FREE(scratch);
    return count;
}
