# Hostname And Network Constraints

| Path | App Limit | Firmware Constraint | Transport |
| --- | --- | --- | --- |
| WBS06 v127 | 48 ASCII bytes for new provisioning | Stock URL/DNS host field is 50 bytes including NUL, yielding a 49-character cutoff | HTTP80 or HTTPS443 |
| WS-30 v102 | 59 ASCII bytes | Patch host buffers and stock resolver buffers are 64 bytes | HTTP80 |

Enter only a DNS hostname or dotted IPv4 address. No scheme, custom port, path, IPv6 literal, trailing dot or Unicode name is accepted by the app. An ASCII/punycode domain must still fit the length limit. WBS06 readback accepts a longer old saved record so it can be diagnosed; a successful readback does not mean the resolver will use the full name. Prefer a short custom domain when a generated hosting hostname is too long.

The Python bridge provisions visible 2.4 GHz WPA2 networks with printable ASCII SSIDs of 1–32 bytes and passwords of 8–63 bytes. Enterprise Wi-Fi, captive portals and WPA3-only networks are outside this workflow.

## Evidence And Extending The Limit

For WBS06, a stored 61-byte hostname was observed in DNS as only its first 49 bytes, resulting in NXDOMAIN. The URL parser at runtime `0x2c7cc` copies the host into a 50-byte field; its following pointer begins at offset `+0x3c`. A second 50-byte copy at `0x2c98c` supplies the HTTP Host header. Increasing one length constant would overwrite adjacent fields. The owner record/readback uses 64-byte buffers, and the network connection routine has a separate `strlen <= 64` guard at `0xcc9a`.

A longer-name patch needs a new connection-target layout, both URL/Host copies, owner-record migration/readback and all consumers audited together. Re-provisioning and DNS/TLS/HTTP tests are necessary. The current 48-byte app cap is deliberately below the observed 49-byte boundary.

WS-30's stock item-2 reader/resolver at `0x1b220` uses adjacent 64-byte stack buffers. Raising its 59-byte patch cap requires stack/frame and WPP response-layout changes.

Addresses are model/source-specific ARM application runtime addresses, not interchangeable file offsets. For these containers, application file offset is `runtime - 0x4000 + 0x84`.
