#!/usr/bin/env python3
"""Single source of truth for the WBS04 (Body Cardio) 2231 port.

Every address is a Thumb VA in the application section, located statically from
the stock image and cross-checked against the WBS06 v1181 patch. See
analysis/FINDINGS.md for how each was derived. The HTTP-only build has been
flashed and verified on a Body Cardio; the HTTPS path is unfinished.

App mapping (same as WBS06): file_off = APP_FILE + VA - APP_VA.
"""
from __future__ import annotations

# --- image / container ---
CDN_URL = "http://cdnfw.withings.net/wbs04/wbs04_2231_1xHtQN.bin"
SOURCE_SIZE = 0xED99C  # 973212
SOURCE_SHA256 = "9668a637640bc031019148a8259c1f740d1517cc61eabbf66a88c549c97d58e1"
SOURCE_SHA1 = "8052ad37991f5eb32ed1e57c9553160f905c4f9f"  # as served by CDN
STOCK_VERSION = 2231
BOOTLOADER = 12

APP_FILE = 0x84
APP_VA = 0x4000
APP_END = 0x880BC  # file offset of section 2 start == end of application bytes

# Proposed YOW version. Kept far below 2231 so the OTHER firmware bank retains a
# vanilla Withings image (dual-slot "lowest version wins"; see README FAQ).
YOW_VERSION = 100

# --- stock helper functions used by the owner injection (thumb VAs) ---
DB_GET = 0x2E33D        # db_get(uint16 item, void* buf, uint16 len)
DB_SET = 0x2E2AD        # db_set(uint16 item, const void* buf, uint16 len)
SETUP_STATE = 0x1B171   # setup_state() -> int (0 = physical setup window open)
REPLY_INIT = 0x68BAD    # reply_init(void* reply)  -- memsets 0xc0, sets [+0xc0]=5
WPP_CONTEXT = 0x47FD9   # wpp_context() -> void*
WPP_REPLY = 0x46F25     # wpp_reply(ctx, uint16 cmd, void* reply, uint32)
MEMSET = 0x6B26F        # memset-like, used by reply_init

# --- DBLIB items ---
HOST_ITEM = 2           # existing stock item holding the server host string
OWNER_ITEM = 0x1F0      # new free item (owner record)
STAGE_ITEM = 0x1F1      # new free item (staged chunked host)

# --- WPP reply struct layout (DIFFERS from WBS06 0x80!) ---
REPLY_LEN_OFFSET = 0xC0  # WBS06 was 0x80
REPLY_BUF_SIZE = 0xC4    # WBS06 was 0x84

# --- patch site 1: URL / HTTP-HTTPS selection ---
URL_HOOK_VA = 0x4B2E8        # BL (stock -> 0x4b120 host-reader); replaced by owner wrapper
URL_HOOK_CMP_VA = 0x4B2F0    # cmp r3,#1 ; ite eq  (http/https select, reused)
URL_HTTPS_POOL_VA = 0x4B3B0  # -> "https://%s/%s" (VA 0x86847)
URL_HTTP_POOL_VA = 0x4B3B4   # -> "http://%s/%s"  (VA 0x86855)

# --- patch site 2: WPP command table + dispatcher ---
TABLE_OLD_VA = 0x44EC
TABLE_OLD_END = 0x4540       # 7 records * 12 bytes
TABLE_CMD_IDS = (0x134, 0x98D, 0x152, 0x156, 0x155, 0x994, 0x993)
DISPATCH_END_POOL_VA = 0x49CC4   # holds TABLE_OLD_END (rewrite to new end)
DISPATCH_START_POOL_VA = 0x49CC8  # holds TABLE_OLD_VA (rewrite to new start)

# --- patch site 3: TLS-accept (HTTPS variant only) ---
TLS_VERIFY_HOOK_VA = 0x2BA0C  # BL x509-verify (0x50d58); replaced by ed25519-accept

# --- patch site 4: server-triggered OTA disable ---
OTA_HANDOFF_BL_VA = 0x4D682   # bl 0x4e040 -> NOP (00bf00bf)
OTA_DRIVER_VA = 0x4E0A0       # push{r3,lr} -> bx lr (7047)

# --- patch site 5: startup face (bitmap byte-identical to WBS06) ---
FACE_DESCRIPTOR_FILE = 0x6CF9C   # (37,26,0,0, ptr)
FACE_BITMAP_VA = 0x89D80
FACE_BITMAP_FILE = 0x85E04
FACE_SIZE = 148
HELLO_SHA256 = "58e2390d0f826fd2dbe96887e2583b5083c425bb280ba958f0d25bf82716c059"


def app_offset(va: int) -> int:
    return APP_FILE + va - APP_VA
