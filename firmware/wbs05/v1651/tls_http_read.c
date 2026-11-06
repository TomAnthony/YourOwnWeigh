/* WBS05 / Body+ v1651 TLS-to-HTTP staging for YOW v100.
 * The stock reader can copy more than its caller's 512-byte buffer capacity.
 * Stage decrypted records in 6 KiB, parse them and free the buffer on all paths.
 * The accompanying record-limit patches cap encrypted records at 4 KiB.
 * Only firmware helpers are mocked in test_tls_http_read.py; the wrapper and
 * this compiled C code execute as ARM instructions in those tests.
 */
#include <stdint.h>

enum { INPUT_CHUNK = 0x200, STAGING_CAP = 0x1800 };

typedef void *(*malloc_t)(uint32_t);
typedef void (*free_t)(void *);
typedef int (*tls_read_t)(void *, uint32_t);
typedef void (*http_parse_t)(void *, void *, const void *, uint32_t);

#define FW_MALLOC ((malloc_t)0x513fd)      /* 0x513fc | thumb */
#define FW_FREE ((free_t)0x5140d)          /* 0x5140c | thumb */
#define FW_TLS_READ ((tls_read_t)0x4e26d)  /* 0x4e26c | thumb */
#define FW_HTTP_PARSE ((http_parse_t)0x7911) /* 0x7910 | thumb */

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
