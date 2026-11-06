"""Pinned WBS05 / Body+ v1651 addresses for the candidate v100 builder.

Application offsets map as APP_FILE + runtime_address - APP_VA.
Callable C helpers below carry the Thumb bit; patch locations do not.
"""

CDN_URL = "http://cdnfw.withings.net/wbs05/wbs05_1651_LJ24pf.bin"
SOURCE_SHA256 = "6bb1e5a6e70853886144b2b73c15450aae0077c60fc243b957dc291c8600efcc"
SOURCE_SHA1 = "8784587d3df5bb645c2c21ee4dc569c762e1e87d"
SOURCE_SIZE = 919180
STOCK_VERSION = 1651
YOW_VERSION = 100
BOOTLOADER = 6
APP_FILE = 0x84
APP_VA = 0x4000
APP_SIZE = 0x7AD28
APP_END = APP_FILE + APP_SIZE
EXTRA = 0x1000
# Keep the manufacturer's reserved word at 0x7fff8 outside the application.
FLASH_LIMIT = 0x7FFF8
MAX_SIZE = 0x190000

DB_GET = 0x2B9C5
DB_SET = 0x2B935
SETUP_STATE = 0x1A1B5
REPLY_INIT = 0x60E55
WPP_CONTEXT = 0x425BD
WPP_REPLY = 0x419B5
REPLY_LEN_OFFSET = 0xC0
REPLY_BUF_SIZE = 0xC4
TABLE_OLD_VA = 0x44B0
TABLE_OLD_END = 0x4504
DISPATCH = 0x43DB4
DISPATCH_END_POOL_VA = 0x43DE8
DISPATCH_START_POOL_VA = 0x43DEC
TABLE_CMD_IDS = (0x134, 0x98D, 0x152, 0x156, 0x155, 0x994, 0x993)
URL_HOOK_VA = 0x45358
URL_HOOK_CMP_VA = 0x45360
OTA_HANDOFF_BL_VA = 0x46BD6
OTA_DRIVER_VA = 0x473F8
RUNTIME_GETTER = 0x19DB8

FACE_BITMAP_VA = 0x7CD75
FACE_SIZE = 148
HELLO_SHA256 = "58e2390d0f826fd2dbe96887e2583b5083c425bb280ba958f0d25bf82716c059"
SMILEY_SHA256 = "dbdadf39ed8c6ad8f0b5abe8dfcb8ff79626dda8925091f20cee603e4e2b23a8"
FACE_DESCRIPTOR_VA = 0x68B18

WRITER_VA = 0x4B12E
WRITER_HELPER = 0x6235C
HTTP_HOOK_VA = 0x2EE0C
HTTP_RESUME_ERR_VA = 0x2EE18
HTTP_RESUME_OK_VA = 0x2EE70
MALLOC = 0x513FC
FREE = 0x5140C
TLS_READ = 0x4E26C
HTTP_PARSE = 0x7910
HTTP_GLOBAL = 0x1FFF4358

# Each replacement is the existing WBS06/WBS04 behavior at a verified WBS05
# instruction. HTTPS encrypts traffic but does not authenticate server identity.
PATCHES = {
    0x4C568: ("68b1", "0de0"),  # skip X.509 callback
    0x4C716: ("7ff4e4ab", "00bf00bf"),  # accept common signature schemes
    0x4C732: ("0ad0", "0ae0"),  # skip Ed25519-only verify path
    0x4C75C: ("7ff4b7ac", "002400bf"),  # clear verification error
    0x4C1D8: ("7ff483ae", "3ff683ae"),  # accept declined MFL negotiation
    0x4CD4A: ("4ff44873", "4ff48053"),  # encrypted limit r3: 800 -> 4096
    0x4CDEE: ("4ff44871", "4ff48051"),  # encrypted limit r1: 800 -> 4096
    OTA_HANDOFF_BL_VA: ("00f0dffb", "00bf00bf"),
    OTA_DRIVER_VA: ("08b5", "7047"),  # retain Bluetooth OTA
}
SIGNATURE_SCHEMES = bytes.fromhex(
    "0403 0503 0603 0804 0805 0806 0809 080a 080b 0401 0501 0601 0807"
)


def app_offset(va):
    return APP_FILE + va - APP_VA
