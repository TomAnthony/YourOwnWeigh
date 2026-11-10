/* Experimental WBS03-only extension. No fixed RAM allocation or global state. */
#define YOW_MULTI_WIFI 1
#include "owner_patch.c"

#define ENTRY __attribute__((section(".text.owner"), used, noinline))
#define INLINE static __attribute__((always_inline)) inline
#define WIFI_ITEM 0x7977
#define PROFILE_SIZE 108
#define MAGIC 0x31465759 /* YWF1 */

INLINE uint32_t checksum(const uint8_t *p) {
    uint32_t h = 2166136261u;
    for (unsigned i = 0; i < 104; ++i) h = (h ^ p[i]) * 16777619u;
    return h;
}
INLINE int valid_profile(const uint8_t *p) {
    if (*(const uint32_t *)p != MAGIC || *(const uint32_t *)(p+104) != checksum(p)
        || p[4] > 1 || p[7] != 0) return 0;
    if (!p[4]) {
        for (unsigned i = 5; i < 104; ++i) if (p[i]) return 0;
        return 1;
    }
    if (p[5] < 1 || p[5] > 32 || p[6] != 7) return 0; /* WPA2 AES */
    for (unsigned i = 0; i < 32; ++i) {
        if (i < p[5]) { if (p[8+i] < 32 || p[8+i] > 126) return 0; }
        else if (p[8+i]) return 0;
    }
    for (unsigned i = 40; i < 104; ++i)
        if (!((p[i] >= '0' && p[i] <= '9') || (p[i] >= 'a' && p[i] <= 'f'))) return 0;
    return 1;
}
INLINE int read_profile(uint8_t *p) {
    for (unsigned i = 0; i < PROFILE_SIZE; ++i) p[i] = 0;
    db_query_t query;
    if (DB_QUERY_OPEN(&query, WIFI_ITEM, PROFILE_SIZE)) return 1;
    int result = DB_QUERY_READ(&query, p);
    unsigned size = query.value_length;
    int closed = DB_QUERY_CLOSE(&query);
    if (result) return result; /* 3 = absent; other errors are not absence. */
    if (closed || size != PROFILE_SIZE || *(uint32_t *)p != MAGIC) return 1;
    return valid_profile(p) ? 0 : 4; /* damaged but recognizably ours */
}

/* This getter is used only by the relocated secondary connection routine.
 * Primary records 9/10/24/27 remain owned by the original firmware. */
ENTRY int secondary_db_get(uint16_t item, uint8_t *dst, uint16_t capacity) {
    uint32_t aligned[PROFILE_SIZE/4];
    uint8_t *p = (uint8_t *)aligned;
    if (item == 9 || item == 0x18) {
        if (read_profile(p) || !p[4]) return 3;
        if ((item == 9 && capacity != 108) || (item == 0x18 && capacity != 80)) return 1;
        for (unsigned i = 0; i < capacity; ++i) dst[i] = 0;
        if (item == 9) {
            for (unsigned i = 0; i < p[5]; ++i) dst[i] = p[8+i];
            *(uint32_t *)(dst+32) = p[5];
            for (unsigned i = 0; i < 64; ++i) dst[36+i] = p[40+i];
            *(uint32_t *)(dst+100) = 64;
            dst[104] = 7;
        } else {
            for (unsigned i = 0; i < 64; ++i) dst[16+i] = p[40+i];
        }
        return 0;
    }
    if (item == 10 && capacity == 22) { /* zeros select DHCP */
        for (unsigned i = 0; i < capacity; ++i) dst[i] = 0;
        return 0;
    }
    if (item == 0x1b) return 3; /* never reuse the primary channel hint */
    return current_db_get(item, dst, capacity);
}

/* Suppress diagnostic/cache writes in the secondary copy. Its PSK already
 * comes from the same atomic record as its SSID, computed by the host. */
ENTRY int secondary_db_set(uint16_t item, const void *value, uint16_t length) {
    (void)item; (void)value; (void)length;
    return 0;
}

ENTRY int wifi_connect_fallback(void *radio, void *network, int *error) {
    typedef int (*connect_t)(void *, void *, int *);
    int first = ((connect_t)0x3a2ad)(radio, network, error);
    if (!first) return first;
    /* Resource/readiness errors are not evidence that another AP can help. */
    if (!error || (*error != 0x3e3 && *error != 0x3e4 && *error != 0x3e2)) return first;
    uint32_t aligned[PROFILE_SIZE/4];
    uint8_t *p = (uint8_t *)aligned;
    if (read_profile(p) || !p[4]) return first;
    uint32_t entry;
    __asm__ volatile ("ldr %0, =0xA1B2C311" : "=r"(entry));
    *error = 0;
    return ((connect_t)entry)(radio, network, error);
}

INLINE void wifi_reply(void *context, uint8_t op, uint8_t status) {
    uint32_t aligned[PROFILE_SIZE/4];
    uint8_t *p = (uint8_t *)aligned;
    unsigned n = 0;
    if (!status) {
        int result = read_profile(p);
        if (result == 3) status = op == 0x10 ? 2 : 3;
        else if (result) status = 3;
        else if (p[4]) n = p[5];
        else if (op == 0x10) status = 2;
    }
    uint8_t frame[45];
    frame[0]=1; frame[1]=1; frame[2]=0x70; frame[3]=0; frame[4]=8+n;
    frame[5]=1; frame[6]=0x70; frame[7]=0; frame[8]=4+n;
    frame[9]=1; frame[10]=op; frame[11]=status; frame[12]=n;
    for (unsigned i=0; i<n; ++i) frame[13+i]=p[8+i];
    RESET_TX(context);
    FRAG_SEND((uint8_t *)context+0x200, frame, 13+n);
}
ENTRY void wifi_reply_read(void *context) { wifi_reply(context, 0x10, 0); }
ENTRY void wifi_reply_write(void *context) { wifi_reply(context, 0x11, 0); }
ENTRY void wifi_reply_failed(void *context) { wifi_reply(context, 0x11, 3); }

/* Owner request 1,0x10,0 reads only the SSID. Write 1,0x11,n,SSID,PSK-hex
 * stores one complete versioned record. Write 1,0x11,0 clears that record.
 * An unrecognized existing item is a collision, never permission to replace. */
ENTRY int wifi_wpp_dispatch(void *context, uint16_t command,
                           const uint8_t *arg, uint32_t length) {
    (void)command;
    if (!arg || length < 7 || arg[0]!=1 || arg[1]!=0x70 || arg[2]!=0 ||
        (unsigned)arg[3]+4 != length || arg[4]!=1) return -1;
    uint32_t callback;
    if (arg[5]==0x10 && length==7 && arg[6]==0) {
        __asm__ volatile ("ldr %0, =0xA1B2C312" : "=r"(callback));
    } else if (arg[5]==0x11 && ((arg[6]==0 && length==7) ||
               (arg[6]>=1 && arg[6]<=32 && length==71u+arg[6]))) {
        uint32_t aligned[PROFILE_SIZE/4], previous[PROFILE_SIZE/4];
        uint8_t *p=(uint8_t *)aligned, *old=(uint8_t *)previous;
        for (unsigned i=0; i<PROFILE_SIZE; ++i) p[i]=0;
        *(uint32_t *)p=MAGIC;
        if (arg[6]) {
            p[4]=1; p[5]=arg[6]; p[6]=7;
            for (unsigned i=0; i<p[5]; ++i) p[8+i]=arg[7+i];
            for (unsigned i=0; i<64; ++i) p[40+i]=arg[7+p[5]+i];
        }
        *(uint32_t *)(p+104)=checksum(p);
        if (!valid_profile(p)) return -1;
        int prior=read_profile(old);
        unsigned same=prior==0;
        for (unsigned i=0; same && i<PROFILE_SIZE; ++i) if (p[i]!=old[i]) same=0;
        int saved=same || ((prior==0 || prior==3 || (prior==4 && !arg[6])) &&
                          DB_SET(WIFI_ITEM,p,PROFILE_SIZE)==0);
        if (saved) {
            saved=read_profile(old)==0;
            for (unsigned i=0; saved && i<PROFILE_SIZE; ++i) if (p[i]!=old[i]) saved=0;
        }
        if (saved) __asm__ volatile ("ldr %0, =0xA1B2C313" : "=r"(callback));
        else __asm__ volatile ("ldr %0, =0xA1B2C314" : "=r"(callback));
    } else return -1;
    *(volatile uint32_t *)((uint8_t *)context+0x198)=callback;
    return 0;
}
