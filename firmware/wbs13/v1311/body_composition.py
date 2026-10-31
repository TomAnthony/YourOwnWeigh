"""WBS13 v1311 body-fat reference, algorithm 0x0D030100 only.

Offline, dependency-free Python translation of the firmware's final regression.
This does not implement sensor acquisition, calibration, or medical validation.
Pass the profile and original measurement inputs explicitly; never substitute
this for a body-fat value supplied by the scale. See BODY_COMPOSITION.md.
"""
from dataclasses import dataclass
from fractions import Fraction
import math
import struct

ALGORITHM = 0x0D030100


def _bits(value):
    return struct.unpack("<f", struct.pack("<I", value))[0]


def f32(value):
    """Round a Python number to IEEE binary32 (nearest, ties to even)."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _rounded(value):
    """Round an exact rational once, including fused multiply/add results.

    Using Python float then struct.pack can double-round an exact halfway
    result. Integer rounding avoids that and does not need a native fmaf library.
    Inputs to the regression are bounded, finite binary32 values.
    """
    if not value:
        return 0.0
    sign = 0x80000000 if value < 0 else 0
    n, d = abs(value).as_integer_ratio()
    exponent = n.bit_length() - d.bit_length()
    below_power = (n < d << exponent) if exponent >= 0 else (n << -exponent < d)
    if below_power:
        exponent -= 1
    shift = max(exponent, -126) - 23
    numerator, denominator = (n, d << shift) if shift >= 0 else (n << -shift, d)
    mantissa, remainder = divmod(numerator, denominator)
    if 2 * remainder > denominator or (2 * remainder == denominator and mantissa & 1):
        mantissa += 1
    if mantissa == 1 << 24:
        exponent += 1
        mantissa >>= 1
    if exponent > 127:
        raise ValueError("binary32 overflow")
    if exponent < -126 and mantissa < 1 << 23:
        return _bits(sign | mantissa)
    return _bits(sign | ((max(exponent, -126) + 127) << 23) | (mantissa & 0x7fffff))


def _add(a, b):
    return _rounded(Fraction(a) + Fraction(b))


def _mul(a, b):
    return _rounded(Fraction(a) * Fraction(b))


def _div(a, b):
    return _rounded(Fraction(a) / Fraction(b))


def _fma(a, b, c):
    """a*b+c with one binary32 rounding, as ARM VFMA.F32."""
    return _rounded(Fraction(a) * Fraction(b) + Fraction(c))


# Literal IEEE binary32 coefficients, ordered by the regression's parameter
# index. Source table addresses are listed here for independent verification.
STANDARD_FEMALE = tuple(map(_bits, (  # 0x0805D110
    0x427B7EAC, 0x46044E8D, 0x40DAEE60, 0xBCD7F12C,
    0x42DCAD4A, 0xC1BB869E, 0x3F40312F, 0x3F89AA08,
    0xBEF5E1C9, 0xC3372F0D, 0xB9D45C19, 0xBA4E5B44,
)))
STANDARD_MALE = tuple(map(_bits, (  # 0x0805D140
    0x425D3EC4, 0x45E48FC8, 0x40C271B1, 0xBCCA2C8E,
    0x43150E5F, 0xC1B07806, 0x3F37FD14, 0x3F8431BD,
    0xBEE2F05B, 0xC32DA5C3, 0xB9CB1579, 0xBA45567D,
)))
MODE1_FEMALE_A = tuple(map(_bits, (  # 0x0805D170
    0xC2A59017, 0x3D3AB8D8, 0x46248CD1, 0x4137E0C6,
    0xC7C9ADCD, 0x43CBE93C, 0x472B9660, 0xCB15D93A,
    0xC5CF54F6, 0x4D4103B4, 0x3C0B26DC, 0xC2B21733,
    0xC6686446,
)))
MODE1_FEMALE_B = tuple(map(_bits, (  # 0x0805D1A4
    0x41EE2BD0, 0x3BDF7693, 0xC63CF231, 0x42145D01,
    0x466D5F5C, 0xC2C55F3B, 0x449F9436, 0x4A40225F,
    0x461C9EF5, 0xCDF63C3C, 0xBDA3E123, 0xC455F333,
    0x4704BEE0,
)))
MODE1_FEMALE_C = tuple(map(_bits, (  # 0x0805D1D8
    0x423082ED, 0x3C1F96B1, 0x44730885, 0x4187F533,
    0x466E112B, 0xC228E8FA, 0xC363A903, 0x493CDA12,
    0x44012A4D, 0xCD915432, 0xBCDF2D13, 0xC4754FD4,
    0x46C02118,
)))
MODE1_MALE_A = tuple(map(_bits, (  # 0x0805D20C
    0xC2E3F201, 0x3E08B059, 0x3EB91910, 0x46B07FC2,
    0xC0D815CA, 0xC2F880F7, 0x43492E13, 0xCCC55E8F,
    0xCA8A5EC2, 0x46F188A4, 0xCAD1AB79, 0xCB3F729C,
    0x46B52D9D, 0x4BB4D7D3, 0x522BA623, 0x435F135D,
    0xC07B6940, 0xC69A1AC4,
)))
MODE1_MALE_B = tuple(map(_bits, (  # 0x0805D254
    0x428D2DCA, 0xBC09309B, 0xBD0A1034, 0x4469273E,
    0x40FA6E2B, 0xC1CDB3D3, 0x4331C868, 0xCC3421C0,
    0xCA2CAF09, 0xC4A9C311, 0x489A0FFC, 0xC92E74A0,
    0xC5A4562E, 0x4CB7D1DA, 0x50F81F53, 0xC5D72846,
    0x4004D4B4, 0x45EC528F,
)))
MODE1_MALE_C = tuple(map(_bits, (  # 0x0805D29C
    0x42834EC4, 0xBC9127B1, 0xBD9A88DD, 0x45806B3E,
    0x4139910E, 0x41C833CA, 0x42B0CA93, 0xCCB6B0F9,
    0xC9AD737E, 0xC3DF16EF, 0x4823983D, 0xC931CB68,
    0x4208B4DF, 0x4C430DAC, 0xD0538F6E, 0xC5995FD3,
    0x3FF6328B, 0x46143ACA,
)))


def _standard(c, height, weight, z6, p6, z50, p50):
    """0x0805CC40: standard-mode fat percentage regression."""
    h2_over_w = _div(_mul(height, height), weight)
    z50_phase = _mul(z50, p50)
    result = _add(_div(c[1], z6), c[0])
    result = _fma(p6, _mul(p6, c[2]), result)
    result = _fma(h2_over_w, c[3], result)
    result = _add(_div(c[4], z50_phase), result)
    result = _add(result, _div(_mul(h2_over_w, c[5]), z50))
    result = _fma(p50, _mul(h2_over_w, c[6]), result)
    result = _fma(p50, _mul(_mul(h2_over_w, c[7]), p50), result)
    result = _add(result, _div(_mul(h2_over_w, c[8]), z50_phase))
    result = _add(_div(_mul(_mul(_mul(h2_over_w, c[9]), p50), p50), z50), result)
    result = _fma(p50, _mul(_mul(h2_over_w, c[10]), z50), result)
    result = _fma(p50, _mul(_mul(_mul(h2_over_w, c[11]), z50), p50), result)
    return min(75.0, max(3.0, result))


def _mode1_female(c, height, weight, z6, z50, p50):
    """0x0805CCFC: one of three mode-1 female regressions."""
    h2 = _mul(height, height)
    result = _fma(z50, c[1], c[0])
    result = _add(_div(c[2], z6), result)
    result = _fma(z50, _div(c[3], z6), result)
    result = _fma(_div(c[4], z6), p50, result)
    result = _fma(p50, c[5], result)
    result = _fma(_div(c[6], h2), weight, result)
    result = _add(_div(_mul(_div(c[7], h2), weight), z6), result)
    result = _fma(p50, _mul(_div(c[8], h2), weight), result)
    result = _fma(p50, _div(_div(c[9], h2), weight), result)
    result = _fma(z50, _div(_mul(weight, c[10]), z6), result)
    result = _fma(z50, _div(_div(c[11], weight), z6), result)
    result = _fma(p50, _div(c[12], weight), result)
    return min(75.0, max(3.0, result))


def _mode1_male(c, height, weight, z6, z50, p50):
    """0x0805CDB0: one of three mode-1 male regressions."""
    h2 = _mul(height, height)
    result = _fma(z50, c[1], c[0])
    result = _fma(_mul(z50, c[2]), p50, result)
    result = _add(_div(c[3], z6), result)
    result = _fma(z50, _div(c[4], z6), result)
    result = _fma(p50, _mul(_div(c[5], z6), z50), result)
    result = _fma(p50, c[6], result)
    result = _add(_div(_div(c[7], h2), z6), result)
    result = _fma(p50, _div(c[8], h2), result)
    result = _fma(_div(c[9], h2), weight, result)
    result = _add(_div(_mul(_div(c[10], h2), weight), z6), result)
    result = _fma(p50, _div(_mul(_div(c[11], h2), weight), z6), result)
    result = _fma(p50, _mul(_div(c[12], h2), weight), result)
    result = _add(_div(_div(c[13], h2), weight), result)
    result = _fma(p50, _div(_div(_div(c[14], h2), weight), z6), result)
    result = _add(_div(c[15], weight), result)
    result = _fma(z50, _div(c[16], weight), result)
    result = _fma(p50, _div(c[17], weight), result)
    return min(75.0, max(3.0, result))


@dataclass(frozen=True)
class FatResult:
    algorithm: int
    fat_percent: float  # Internal result, before mass quantization.
    fat_mass_kg: float  # Internal float32 mass.
    uploaded_fat_mass_value: int  # Type 8, unit -2: trunc(float32(kg * 100)).


def calculate_fat(*, algorithm, sex, body_mode, age_years, height_m,
                  weight_kg, impedance_6250_ohm, impedance_50000_ohm):
    """Reproduce WBS13's final fat calculation for known, valid inputs.

    sex: firmware 0 (male) or 1 (female).
    body_mode: explicit 0 or 1 from user feature tag 67; not fatmethod `fm`.
    age_years: profile age; the fat regression only uses it for validation.
    height_m: stored profile float32 metres; firmware multiplies by 100.
    weight_kg: the original float32 weight, before HTTP rounding to 0.001 kg.
    impedances: already calibrated whole-ohm record values (HTTP types 189/177).

    Measured phase is deliberately NOT an input: this WBS13 wrapper supplies
    the constants -0.04552/-0.10345 radians. The 250-kHz reading is also unused
    by this final fat formula. Reject unknown algorithms and profile modes.
    The library's input-warning cases are rejected instead of producing an
    apparently valid server estimate; this reference is not sensor validation.
    """
    if type(algorithm) is not int or algorithm != ALGORITHM:
        raise ValueError("only WBS13 algorithm 0x0D030100 is supported")
    if type(sex) is not int or sex not in (0, 1):
        raise ValueError("sex must be the explicit firmware code 0 or 1")
    if type(body_mode) is not int or body_mode not in (0, 1):
        raise ValueError("body_mode must be explicitly known as 0 or 1")
    values = (age_years, height_m, weight_kg, impedance_6250_ohm, impedance_50000_ohm)
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError("all profile and measurement inputs must be finite numbers")
    try:
        age, metres, weight, z6, z50 = map(f32, values)
        height = _mul(metres, 100.0)
    except (OverflowError, ValueError) as exc:
        raise ValueError("inputs exceed binary32 range") from exc
    # 0x0805CAB8 validation bounds; phases are the wrapper's known constants.
    if not (18 <= age <= 99 and 90 <= height <= 250 and 20 <= weight <= 270
            and 309 <= z6 <= 1038 and 273 <= z50 <= 893):
        raise ValueError("inputs outside the firmware's validated ranges")
    ratio = _div(z50, z6)
    if not _bits(0x3F53CAEA) <= ratio <= _bits(0x3F75806F):
        raise ValueError("impedance ratio outside the firmware's validated range")
    p6, p50 = _bits(0xBD3A732E), _bits(0xBDD3DD98)
    if body_mode == 0:
        coefficients = STANDARD_MALE if sex == 0 else STANDARD_FEMALE
        percent = _standard(coefficients, height, weight, z6, p6, z50, p50)
    else:
        calculate = _mode1_male if sex == 0 else _mode1_female
        tables = ((MODE1_MALE_A, MODE1_MALE_B, MODE1_MALE_C) if sex == 0 else
                  (MODE1_FEMALE_A, MODE1_FEMALE_B, MODE1_FEMALE_C))
        percent = min(calculate(c, height, weight, z6, z50, p50) for c in tables)
    mass = _div(_mul(weight, percent), 100.0)  # 0x0805D2E4.
    return FatResult(ALGORITHM, percent, mass, int(_mul(mass, 100.0)))
