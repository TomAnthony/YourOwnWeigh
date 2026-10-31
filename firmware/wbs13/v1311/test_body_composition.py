"""Synthetic regression vectors; no firmware download, credentials or hardware.

Run: python -m unittest discover -s firmware/wbs13/v1311 -p test_body_composition.py
The expected values were independently obtained from the original ARM routines;
verify_body_composition.py compares a much larger set against an owner's image.
"""
from fractions import Fraction
import math
import unittest

from body_composition import ALGORITHM, _fma, _rounded, calculate_fat, f32

BASE = dict(algorithm=ALGORITHM, sex=0, body_mode=0, age_years=40.25,
            height_m=1.75, weight_kg=80.5,
            impedance_6250_ohm=550, impedance_50000_ohm=500)


class BodyCompositionTests(unittest.TestCase):
    def test_firmware_vectors_all_sex_and_mode_branches(self):
        for sex, mode, percent, mass, wire in (
            (0, 0, 23.42301368713379, 18.855525970458984, 1885),
            (0, 1, 16.654788970947266, 13.407105445861816, 1340),
            (1, 0, 31.527509689331055, 25.37964630126953, 2537),
            (1, 1, 27.4100399017334, 22.065082550048828, 2206),
        ):
            with self.subTest(sex=sex, mode=mode):
                result = calculate_fat(**dict(BASE, sex=sex, body_mode=mode))
                self.assertEqual(result.fat_percent, percent)
                self.assertEqual(result.fat_mass_kg, mass)
                self.assertEqual(result.uploaded_fat_mass_value, wire)

    def test_reject_unknown_algorithm_or_mode(self):
        for change in ({'algorithm': 0}, {'algorithm': '218300672'},
                       {'body_mode': None}, {'body_mode': 2}, {'sex': 2},
                       {'body_mode': True}, {'sex': False}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                calculate_fat(**dict(BASE, **change))

    def test_missing_inputs_are_not_invented(self):
        for key in BASE:
            values = dict(BASE)
            del values[key]
            with self.subTest(key=key), self.assertRaises(TypeError):
                calculate_fat(**values)

    def test_reject_missing_nonfinite_and_out_of_range_values(self):
        for key, values in (
            ('age_years', [None, 17, 100, math.nan]),
            ('height_m', [0, .8, 3, math.inf]),
            ('weight_kg', [-1, 19, 271, 1e300]),
            ('impedance_6250_ohm', [0, 308, 1039, '550']),
            ('impedance_50000_ohm', [200, 894, 600]),
        ):
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    calculate_fat(**dict(BASE, **{key: value}))

    def test_wire_mass_is_truncated_not_rounded(self):
        result = calculate_fat(**BASE)
        self.assertEqual(result.uploaded_fat_mass_value, 1885)
        self.assertEqual(round(result.fat_mass_kg * 100), 1886)
        self.assertNotEqual(result.fat_percent, 100 * (1885 / 100) / BASE['weight_kg'])

    def test_fused_operation_rounds_only_once(self):
        a, b = f32(1 + 2 ** -23), f32(1 - 2 ** -23)
        self.assertEqual(_fma(a, b, -1.0), -(2 ** -46))
        self.assertEqual(f32(f32(a * b) - 1), 0)

    def test_ties_to_even_and_subnormals(self):
        self.assertEqual(_rounded(Fraction(1) + Fraction(1, 2 ** 24)), 1.0)
        self.assertEqual(_rounded(Fraction(1) + Fraction(3, 2 ** 24)), 1 + 2 ** -22)
        self.assertEqual(_rounded(Fraction(1, 2 ** 150)), 0.0)
        self.assertEqual(_rounded(Fraction(3, 2 ** 150)), 2 ** -148)
        self.assertEqual(_rounded(-Fraction(3, 2 ** 150)), -(2 ** -148))


if __name__ == '__main__':
    unittest.main()
