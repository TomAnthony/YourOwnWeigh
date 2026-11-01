/* WBS04 (Body Cardio) TLS-to-HTTP receive staging — port of the WBS06 v126 shim.
 *
 * Why this exists, in plain terms: the stock firmware reads decrypted HTTPS data
 * into a small 512-byte area and hands it straight to the HTTP parser. Once the
 * TLS fragment stage raises the record size to 4 KiB, a single decrypted record
 * can be bigger than that 512-byte area. This function instead reads into its
 * own larger scratch buffer, passes everything to the unchanged HTTP parser, and
 * frees the buffer again. It is called only from the HTTP receive loop.
 *
 * Every address below is a WBS04 firmware location, verified by disassembly
 * against the byte-identical WBS06 receive loop (see analysis/FINDINGS.md). The
 * connection-struct offsets 0x238/0x258 matched WBS06 exactly.
 */
#include <stdint.h>

enum { INPUT_CHUNK = 0x200, STAGING_CAP = 0x1800 };

typedef void *(*malloc_t)(uint32_t);
typedef void (*free_t)(void *);
typedef int (*tls_read_t)(void *, uint32_t);
typedef void (*http_parse_t)(void *, void *, const void *, uint32_t);

#define FW_MALLOC ((malloc_t)0x585b5)      /* 0x585b4 | thumb */
#define FW_FREE ((free_t)0x585c5)          /* 0x585c4 | thumb */
#define FW_TLS_READ ((tls_read_t)0x54f59)  /* 0x54f58 | thumb */
#define FW_HTTP_PARSE ((http_parse_t)0x7d81) /* 0x7d80 | thumb */

__attribute__((section(".text.v100"), used, noinline))
int v100_http_read_parse(void *const *connection_slot) {
    uint8_t *scratch = (uint8_t *)FW_MALLOC(STAGING_CAP);
    if (!scratch) return -8;

    int count = FW_TLS_READ(scratch, INPUT_CHUNK);
    if (count >= 0) {
        /* The fragment stage caps an encrypted record at 4096 bytes. At most one
         * partial record is buffered between reads; adding 512 input bytes stays
         * under STAGING_CAP (6144). */
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
