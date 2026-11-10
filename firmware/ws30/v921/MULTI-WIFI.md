# Two Wi-Fi networks: feasibility investigation

Status, 10 November 2026: not implemented, not flashed. YOW 102 remains the
hardware-tested firmware. No network has been replaced for this investigation.

## Evidence from the pinned stock v921 image

- Application mapping: file offset 0x84 maps to Thumb virtual address 0x4000.
- WPP dispatcher 0x1b2e8 handles command 0x103 through parser 0x50bba.
- The parser keeps one 0x104 SSID/key TLV. Its already-seen guard at 0x50c72
  ignores a second one. This was executed with Unicorn, not just inferred from
  strings: swapping the two TLVs swaps the selected network, never stores both.
- The read callback at 0x1b190 reads DBLIB item 9, capacity 0x6c (108 bytes).
  The record contains SSID[32], a 32-bit length at +0x20, key[64] at +0x24,
  a 32-bit key length at +0x64, and authentication fields starting at +0x68.
  The parser layout is covered by the executable characterization test.
- Connection routine 0x3a2ac reads item 9, derived-key cache item 0x18 (80
  bytes), network settings item 10 (22 bytes) and a hint in item 0x1b (4 bytes).
  A missing derived-key cache calls 0x2f9d8. A successful cache calculation may
  persist item 0x18 at 0x3a490. A second SSID must not reuse the first SSID's PSK.
- Calls to 0x3a2ac occur at 0x7de0, 0x16688 and 0x50852. The routine has cleanup
  paths that call 0x2dec8; calling it twice without studying radio lifecycle is
  not established to be safe. These addresses are version-specific findings,
  not a public API or already-qualified patch locations.

Run characterization with private firmware and synthetic credentials:

```powershell
$env:YOW_WBS03_STOCK='local/firmware/stock/4eb3f9a5390faae2c11421ac388e5450bddc31449f3153f59daca1b10b0eaf48.bin'
.venv/Scripts/python.exe -m unittest discover -s tools -p test_ws30_wifi.py -v
```

## Proposed behavior

Keep the current network as primary. Add one separately persisted secondary
SSID/key, written over an extension of the owner Bluetooth protocol. A normal
sync tries primary, then secondary if association fails; both failing must end
the attempt within a bounded battery budget. Once either works, keep the normal
YOW HTTP protocol and queued-measurement acknowledgements unchanged.

Use RAM for per-attempt state and avoid flash writes on every network attempt.
Store credentials separately from firmware bytes, repository history and logs.
Do not claim multi-network support merely by backing up profiles on the PC.

## Work still required before building a flashable candidate

1. Map the three callers, radio initialization/cleanup, error codes and retry
   scheduler. Decide the correct fallback hook; do not blindly retry the
   low-level association routine after it has torn down its context.
2. Find and verify an unused DB item and its maximum size/transaction behavior.
   Define versioned profile encoding, validation, atomic writes and readback
   that never returns keys. Preserve the primary profile and caches on errors.
3. Isolate derived PSK, network/DHCP and channel hints for the alternate network.
   Emulate both attempts, radio cleanup and storage failures.
4. Extend the Bluetooth owner command, Python bridge and UI for two profiles.
   Maintain the existing single-network behavior when no secondary is set.
5. Build from the pinned image with all bootloader/radio/container checks; test
   no-network, primary-only, secondary-only, bad key, both-present, power cycle
   and normal OTA downgrade. Then qualify on hardware, including battery impact.

The radio remains 2.4 GHz. A software patch cannot add a 5 GHz radio. Verify the
secondary access point's 2.4 GHz availability before treating failed association
as a firmware defect.
