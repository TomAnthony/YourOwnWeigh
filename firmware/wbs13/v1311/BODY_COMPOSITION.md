# WBS13 Body-Fat Calculation

The final body-fat calculation is reproducible for **WBS13 stock 1311 / YOW 100,
algorithm `0x0D030100` (`218300672`)**. The dependency-free
[Python reference](body_composition.py) matches the original ARM routines
bit-for-bit across both sex codes and both body-mode branches. The existing
firmware already uploads its calculated fat mass, so the server should retain
that authoritative value rather than replace it with a recalculation.

This analysis covers the final regression. Sensor acquisition, electrode quality,
MAX30009 calibration and biological accuracy are outside its scope. The
reference is a developer tool, not a new firmware patch or a production fallback.

## Inputs And Data Flow

The normal weigh-in path calls `0x0801361C`, which builds this 32-byte input
structure and passes it to `0x08013424`:

| Offset | Input | Source |
|---|---|---|
| `0x00` | Sex, byte `0` or `1` | User record `sx` at `+0x1D`; zero/nonzero normalised |
| `0x01` | Body mode, byte `0` or `1` | User feature-tag lookup `0x0802B29C`, tag **67** |
| `0x04` | Age, float32 years | User record `agt` at `+0x25` |
| `0x08` | Height, float32 centimetres | Stored float32 metres at `+0x21`, multiplied by 100 |
| `0x0C` | Weight, float32 kg | Measurement record `+0x15`, before upload rounding |
| `0x10` | 6.25-kHz impedance magnitude, float32 ohms | Whole-ohm int16 at measurement `+0x1B`; uploaded type **189**, unit `0` |
| `0x14` | 6.25-kHz phase, float32 radians | Fixed bits `0xBD3A732E` (approximately `-0.04552`) |
| `0x18` | 50-kHz impedance magnitude, float32 ohms | Whole-ohm int16 at measurement `+0x1D`; uploaded type **177**, unit `0` |
| `0x1C` | 50-kHz phase, float32 radians | Fixed bits `0xBDD3DD98` (approximately `-0.10345`) |

The frequency-selector table at `0x0807FD60`, indexed by `0x08045230`, confirms
selector 7 = 6,250 Hz, 3 = 50,000 Hz and 10 = 250,000 Hz. The normal acquisition
order at `0x08087133` is `6,7,3,4,10,11,12`. This accounts for the record offsets
and the uploaded 250-kHz magnitude, type **178**, which the final fat regression
does not consume.

The measured phases are uploaded separately as types **201**, **202** and
**203**, with unit `-3`. They are milliradian-scaled values: the wrapper converts
its centidegree records by multiplying by float32 pi and dividing by 18, then
truncates the integer payload. However, the normal weigh-in calculation uses
the two fixed phase constants above. Changing those measured phase records in
an emulated normal weigh-in leaves the calculation inputs and fat result
unchanged. The UART `suizei` diagnostic paths can supply other phases; they are
not the normal weigh-in path represented by this reference.

The profile's `fm` (fatmethod) is **not** the body-mode selector in this path.
Changing `fm` leaves these inputs unchanged. The firmware itself calls the flag
`body_mode`; tag 67's mapping to a user-facing name such as athlete mode has not
been independently established. The reference requires an explicit `0` or `1`
instead of guessing from `fm` or a person's weight.

## Regression And Rounding

`0x0805CC38` returns the algorithm ID. Percentage entry `0x0805CEA0` selects:

- **Mode 0:** one sex-specific 12-coefficient regression at `0x0805CC40`.
  It uses height squared divided by weight, both impedances, the fixed phases
  and their products/ratios. Age participates in validation, not this equation.
- **Mode 1, sex 1:** three 13-coefficient regressions at `0x0805CCFC`.
- **Mode 1, sex 0:** three 18-coefficient regressions at `0x0805CDB0`.

Each regression clamps its result to **3–75%**. Mode 1 takes the minimum of its
three clamped results (`0x08079002`). Literal coefficients and exact operation
ordering are recorded in the reference, with their source table addresses.
All arithmetic is IEEE binary32; fused multiply-add rounds once, not after the
multiplication and again after addition.

Mass entry `0x0805D2E4` then computes:

```text
fat_mass_kg = float32(float32(weight_kg * fat_percent) / 100)
```

The outer wrapper at `0x080134E0` stores:

```text
uploaded_type_8_value = truncate_toward_zero(float32(fat_mass_kg * 100))
unit = -2
```

This is truncation to a hundredth of a kilogram, not ordinary decimal rounding.
The same wrapper calculates fat-free, water, muscle, bone, visceral fat, BMR
and metabolic age through other library entry points. A replay with the private
recognised capture reproduced **all eight transmitted values** after their
respective quantization, using both stock and patched images.

Validation at `0x0805CAB8` checks profile, impedance and phase ranges. The
reference rejects inputs outside these ranges instead of reproducing warning
results. The full wrapper additionally combines flags from all eight metric
calculations, stores the resulting status as type **207**, and suppresses
composition outputs when status bits `0x11` are set. A valid result from the
isolated fat regression is therefore not proof that the full scale acquisition
would accept that measurement. Do not use the reference to bypass a failed
measurement status.

## What The Server Can Reconstruct

There are three distinct values:

1. **Uploaded fat mass:** type 8 multiplied by `10^unit`. This is already
   calculated by the scale and is the value to store and expose.
2. **Percentage derived from uploads:** `100 * fat_mass_kg / weight_kg` is a
   useful derived percentage, but both inputs have been quantized. It should be
   labelled derived, not presented as the exact internal firmware percentage.
3. **Firmware regression replay:** this reference calculates the internal
   percentage/mass when the exact inputs and body mode are known.

A general server replay cannot promise bit-identical results from the upload
alone. Weight serialization at `0x08046BE6` rounds the original float32 weight to
0.001 kg using a fused `weight * 1000 + 0.5` followed by integer conversion. The
unrounded weight is not transmitted. Body mode also is not present in the
captured upload; it comes from the profile's feature tags. Historical profile
height/sex must match those on the scale at measurement time. A successful
match on the captured test does not remove these information gaps.

The reference requires the algorithm ID, profile values, body mode and both
impedances explicitly. It rejects unknown algorithm IDs and does not silently
substitute defaults. Its exact rational rounding helpers make it portable
without NumPy, a vendor library or a firmware image at runtime. A TypeScript
translation is possible, but simply replacing operations with JavaScript
arithmetic or `Math.fround(a*b+c)` is not a complete guarantee of exact ARM FMA
rounding. The existing uploaded result avoids that additional complexity.

**Do not apply this WBS13 formula to WS-50/WBS02 or other models.** A matching
formula needs those models' own algorithm ID, inputs and regression evidence;
a shared measurement type number does not establish a shared calculation.

## Verification

Run the synthetic known-answer and input-contract tests with standard Python:

```sh
python3 -m unittest discover -s firmware/wbs13/v1311 -p test_body_composition.py
```

For independent comparison with the firmware, install Unicorn in a development
environment and supply the privately held vendor image:

```sh
python firmware/wbs13/v1311/verify_body_composition.py /path/to/wbs13_1311_lb2w93.bin
```

The verifier refuses unknown hashes, performs no hardware/network access and
uses only synthetic inputs. The recorded run checked **1,000 cases per image**
across all four sex/mode combinations, comparing percentage and mass bit-for-bit.
It also ran 40 cases per image through the normal wrapper, checking fixed-phase
inputs, independence from `fm`, output suppression and mass quantization.
Both stock 1311 and YOW 100 passed. The unit tests include a fused-rounding case,
ties-to-even, subnormal results, known answers for all four branches and rejected
missing/unsupported inputs. These are software equivalence tests, not an
assessment of the device's biological measurement accuracy.
