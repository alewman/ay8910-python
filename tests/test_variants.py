"""The parts and their DAC tables."""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

from ay8910_python import (
    AY8910,
    AY8912,
    AY8913,
    DAC_5B,
    DAC_AY_LOGARITHMIC,
    DAC_AY_MEASURED,
    DAC_YM_DATASHEET,
    DAC_YM_MEASURED,
    SUNSOFT_5B,
    VARIANTS,
    YM2149,
)


def decibels(table: tuple[float, ...], code: int) -> float:
    return 20 * math.log10(table[code] / table[code - 1])


def test_the_five_parts() -> None:
    assert list(VARIANTS) == ["AY-3-8910", "AY-3-8912", "AY-3-8913", "YM2149", "Sunsoft 5B"]
    assert all(VARIANTS[variant.name] is variant for variant in VARIANTS.values())


def test_what_differs_between_the_parts() -> None:
    assert [v.envelope_steps for v in (AY8910, AY8912, AY8913, YM2149, SUNSOFT_5B)] == [
        16, 16, 16, 32, 32,
    ]  # fmt: skip
    assert [v.ports for v in (AY8910, AY8912, AY8913, YM2149, SUNSOFT_5B)] == [
        "AB", "A", "", "AB", "",
    ]  # fmt: skip
    assert [v.clock_divider for v in VARIANTS.values()] == [1, 1, 1, 1, 2]
    assert [v.has_sel_pin for v in VARIANTS.values()] == [False, False, False, True, False]
    assert [v.codes for v in VARIANTS.values()] == [16, 16, 16, 32, 32]
    assert AY8910.register_masks[1] == 0x0F and YM2149.register_masks[1] == 0xFF


@pytest.mark.parametrize(
    "table", [DAC_AY_MEASURED, DAC_AY_LOGARITHMIC, DAC_YM_MEASURED, DAC_YM_DATASHEET, DAC_5B]
)
def test_a_dac_table_rises_from_silence_to_one(table: tuple[float, ...]) -> None:
    assert len(table) in (16, 32)
    assert table[0] == 0.0 and table[-1] == pytest.approx(1.0)
    assert all(low <= high for low, high in pairwise(table))


def test_the_ladders_are_3_db_a_volume_and_half_that_an_envelope_step() -> None:
    for code in range(2, 16):
        assert decibels(DAC_AY_LOGARITHMIC, code) == pytest.approx(3.0103, abs=1e-4)
    for code in range(3, 32):
        assert decibels(DAC_YM_DATASHEET, code) == pytest.approx(1.50515, abs=1e-5)
    # The catalog's own figures, Fig. 1.
    for code, volts in ((31, 1.0), (30, 0.841), (29, 0.707), (28, 0.595), (27, 0.5), (19, 0.125)):
        assert DAC_YM_DATASHEET[code] == pytest.approx(volts, abs=5e-4)
    assert DAC_YM_DATASHEET[1] == 0.0  # a volume of 0 drives code 1: silence


def test_how_far_the_measured_tables_stand_from_the_ladders() -> None:
    # The AY's measured levels sit above the 3 dB ladder everywhere below the top,
    # by up to 4.8 dB; the YM2149's stay within 2.6 dB of Yamaha's from code 4 up.
    ay = [20 * math.log10(DAC_AY_MEASURED[c] / DAC_AY_LOGARITHMIC[c]) for c in range(1, 16)]
    assert min(ay) >= 0.0 and 4.7 < max(ay) < 4.8
    ym = [20 * math.log10(DAC_YM_MEASURED[c] / DAC_YM_DATASHEET[c]) for c in range(4, 32)]
    assert min(ym) >= 0.0 and max(ym) < 2.6


def test_a_yamaha_volume_lands_on_the_ays_3_db_steps() -> None:
    # Volume v drives code 2v + 1, two 1.5 dB steps apart: the AY's ladder.
    for volume in range(2, 16):
        step = 20 * math.log10(DAC_5B[2 * volume + 1] / DAC_5B[2 * volume - 1])
        assert step == pytest.approx(3.0103, abs=1e-4)


def test_the_measured_ay_table_is_westcotts_voltages() -> None:
    low, high = 1.147, 2.58
    assert DAC_AY_MEASURED[8] == pytest.approx((1.336 - low) / (high - low))
    assert DAC_AY_MEASURED[1] == pytest.approx((1.162 - low) / (high - low))
