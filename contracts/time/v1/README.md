# Clock Contract

The server owns timezone/DST calculation. It returns `utcSeconds`, signed `goff`, unsigned `dst` (next transition UTC, or zero), and signed `ngoff`. Python encodes these as big-endian `uint32, int32, uint32, int32` in WPP command/TLV `0x501`.

`vectors.json` independently derives expected values from Python's standard `zoneinfo` database for fixed UTC instants. TypeScript tests compare `zoneTriplet`; Python tests check only wire encoding. Europe/Berlin cases straddle both transitions, and other cases cover UTC, fractional offsets and the southern hemisphere. This avoids maintaining DST arithmetic in two runtimes.

Current UTC is generated for each request/session; never replay captured vendor UTC. IANA rule changes require refreshing fixtures deliberately where historical expectations actually change.
