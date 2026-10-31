/* WBS13 v1311 owner-server TLS adapters. Build-time addresses are model-pinned.
 *
 * The stock reader consumes an entire TLS record into its caller's buffer.
 * That caller normally supplies only 0x21a bytes inside a connection object.
 * Increasing the record limit therefore also requires separate staging and
 * delivering the complete plaintext to the existing streaming HTTP parser.
 * No persistent RAM or device-specific credentials are added to the image.
 */
#include <stdint.h>

enum { STAGING_CAP = 0x1100 };
typedef void *(*malloc_t)(uint32_t);
typedef void (*free_t)(void *);
typedef int (*tls_read_t)(void *);
typedef void (*http_parse_t)(void *, void *, const void *, uint32_t);
typedef int (*owner_enabled_t)(void);
typedef int (*client_init_t)(void *);

#define FW_MALLOC ((malloc_t)0x08066695)
#define FW_FREE ((free_t)0x080666a5)
#define FW_TLS_READ ((tls_read_t)0x0805eafd)
#define FW_HTTP_PARSE ((http_parse_t)0x08050445)
#define FW_CLIENT_INIT ((client_init_t)0x08070f1b)
#define OWNER_ENABLED ((owner_enabled_t)OWNER_ENABLED_VA)

__attribute__((section(".text.owner_tls_init"), used, noinline))
int yow_tls_client_init(uint32_t *context) {
    if (!OWNER_ENABLED()) return FW_CLIENT_INIT(context);

    /* Owner HTTPS follows the existing YOW encrypted-only policy. Do not load
     * or offer the factory client identity to an owner-selected endpoint. The
     * original verifier and client identity remain active without an owner
     * target. Factory DBLIB records themselves are never modified here. */
    context[0x24 / 4] = 0;  /* verify_certificate */
    context[0x10 / 4] = 0;  /* certificate iovec */
    context[0x14 / 4] = 0;  /* certificate count */
    context[0x20 / 4] = 0;  /* sign_certificate */
    return 0;
}

__attribute__((section(".text.owner_tls_read"), used, noinline))
int yow_tls_http_read_parse(void *const *connection_slot) {
    uint8_t *scratch = (uint8_t *)FW_MALLOC(STAGING_CAP);
    if (!scratch) return -8;
    int count = FW_TLS_READ(scratch);
    if (count >= 0) {
        /* The patched record reader rejects total records above 0x1005,
         * including the five-byte header, before reading their payload. */
        if ((uint32_t)count > STAGING_CAP || !*connection_slot) {
            count = -8;
        } else {
            uint8_t *connection = (uint8_t *)*connection_slot;
            FW_HTTP_PARSE(connection + 0x250, connection + 0x270,
                          scratch, (uint32_t)count);
        }
    }
    FW_FREE(scratch);
    return count;
}
