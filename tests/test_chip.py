"""The contract: time, the bus, the generators and the outputs (docs/contract.md).

These are the chip's rules stated as tests, each one small enough to read. That
the rules are the die's is the referee's business (tests/test_referee.py,
docs/validation.md); these keep them from drifting, and are the gate the seeded
faults are run against (scripts/mutation.py).
"""

from __future__ import annotations

import pytest

from ay8910_python import (
    AY8910,
    AY8912,
    AY8913,
    CLOCKS_PER_STEP,
    COUNT_PHASE,
    PSG,
    STROBE_PHASE,
    SUNSOFT_5B,
    VARIANTS,
    YM2149,
)


def runs(values: list[int]) -> list[tuple[int, int]]:
    """A sequence as (value, length) runs."""
    found: list[tuple[int, int]] = []
    for value in values:
        if found and found[-1][0] == value:
            found[-1] = (value, found[-1][1] + 1)
        else:
            found.append((value, 1))
    return found


def channel_a(chip: PSG, clocks: int) -> list[int]:
    chip.run(clocks)
    return [a for a, _, _ in chip.take_outputs()]


def tone_chip(variant=AY8910, period: int = 3, volume: int = 15) -> PSG:
    chip = PSG(variant)
    chip.write_register(7, 0x3E)  # tone A alone
    chip.write_register(8, volume)
    chip.write_register(0, period & 0xFF)
    chip.write_register(1, period >> 8)
    return chip


# -- time ------------------------------------------------------------------------------


def test_one_output_per_input_clock() -> None:
    chip = PSG()
    chip.run(5)
    assert len(chip.take_outputs()) == 5
    assert chip.take_outputs() == []
    assert chip.clock == 5


def test_run_is_tick_that_many_times() -> None:
    ticked, run = tone_chip(SUNSOFT_5B, 2), tone_chip(SUNSOFT_5B, 2)
    polled = []
    for _ in range(300):
        ticked.tick()
        polled.append(ticked.levels())
    run.run(300)
    assert polled == run.take_outputs() == ticked.take_outputs()
    assert ticked.clock == run.clock == 300


def test_record_off_queues_nothing() -> None:
    chip = PSG(record=False)
    chip.run(100)
    assert chip.take_outputs() == []
    assert chip.clock == 100


def test_silent_after_reset() -> None:
    chip = PSG()
    chip.run(1000)
    assert set(chip.take_outputs()) == {(0, 0, 0)}


def test_the_strobe_then_the_count() -> None:
    assert (STROBE_PHASE, COUNT_PHASE, CLOCKS_PER_STEP) == (2, 3, 8)


@pytest.mark.parametrize("period", [1, 2, 3, 7, 100, 0xFFF])
def test_a_tone_is_high_and_low_for_eight_clocks_a_count(period: int) -> None:
    chip = tone_chip(period=period)
    chip.run(8 * period * 3)
    chip.take_outputs()
    lengths = {length for _, length in runs(channel_a(chip, 8 * period * 6))[1:-1]}
    assert lengths == {8 * period}


def test_tone_period_0_is_period_1() -> None:
    assert channel_a(tone_chip(period=0), 400) == channel_a(tone_chip(period=1), 400)


def test_the_first_edges_after_reset() -> None:
    # The tones are high out of /RESET; held counters cannot expire at the first
    # strobe (clock 2), count on clock 3 and expire on clock 10.
    chip = PSG()
    chip.write_register(7, 0x3E)
    chip.write_register(8, 15)
    assert channel_a(chip, 20) == [15] * 10 + [0] * 8 + [15] * 2


def test_a_tone_cannot_be_restarted_by_writing_it() -> None:
    chip = tone_chip(period=5)
    plain = channel_a(chip, 600)
    chip = tone_chip(period=5)
    rewritten = []
    for _ in range(60):
        chip.write_register(0, 5)
        chip.write_register(1, 0)
        rewritten += channel_a(chip, 10)
    assert rewritten == plain


def test_a_shorter_period_ends_the_half_cycle_at_the_next_strobe() -> None:
    chip = tone_chip(period=40)
    chip.run(8 * 40 * 2 + 4)  # just past an edge and the count: phase 4, count 1
    chip.run(8 * 20)  # count 21
    chip.take_outputs()
    chip.write_register(0, 5)
    assert [length for _, length in runs(channel_a(chip, 100))][:2] == [6, 40]


def test_a_period_written_while_the_strobe_is_open_is_compared_at_once() -> None:
    def edge_after(write_at: int) -> int:
        chip = tone_chip(period=40)
        chip.run(8 * 40 * 2 + 3 + 8 * 20)  # phase 3 of the divider, count 21
        chip.take_outputs()
        chip.run(write_at)
        chip.write_register(0, 5)
        chip.run(40 - write_at)
        out = [a for a, _, _ in chip.take_outputs()]
        return next(i for i in range(1, 40) if out[i] != out[i - 1])

    # Phase 3 is the clock after the strobe's: the strobe is still open and the
    # edge comes with the write itself. A clock later it waits for the next one.
    assert edge_after(8) == 8
    assert edge_after(9) == 15


def test_the_volume_and_the_mixer_act_at_once() -> None:
    chip = PSG()
    chip.write_register(7, 0x3F)
    for volume in range(16):
        chip.write_register(8, volume)
        assert chip.levels() == (volume, 0, 0)
    chip.write_register(7, 0x3E)  # the tone is high out of reset
    chip.write_register(8, 9)
    assert chip.levels()[0] == 9


# -- the noise -------------------------------------------------------------------------


def noise_bits(period: int, shifts: int, variant=AY8910) -> list[int]:
    """The noise as channel A hears it, one value per shift."""
    chip = PSG(variant)
    chip.write_register(7, 0x37)
    chip.write_register(8, 15)
    chip.write_register(6, period)
    step = 16 * max(period, 1) * variant.clock_divider
    chip.run(step * 4)
    chip.take_outputs()
    chip.run(step * shifts)
    return [1 if a else 0 for a, _, _ in chip.take_outputs()[step - 1 :: step]]


def lfsr(shifts: int, skip: int = 0) -> list[int]:
    """A 17-bit register shifting left, fed bit 16 XOR bit 13, started from the
    single 1 the chip puts into an empty register; heard inverted at bit 16."""
    register, out = 1, []
    for index in range(skip + shifts):
        if index >= skip:
            out.append((~register >> 16) & 1)
        register = ((register << 1) | ((register >> 16) ^ (register >> 13)) & 1) & 0x1FFFF
    return out


def test_the_noise_is_the_17_bit_register_tapped_at_16_and_13() -> None:
    heard = noise_bits(1, 400)
    assert any(heard == lfsr(400, skip) for skip in range(40))


def test_the_noise_steps_every_sixteen_clocks_a_count() -> None:
    for period in (1, 2, 5, 31):
        chip = PSG()
        chip.write_register(7, 0x37)
        chip.write_register(8, 15)
        chip.write_register(6, period)
        chip.run(16 * period * 50)
        chip.take_outputs()
        lengths = {length for _, length in runs(channel_a(chip, 16 * period * 300))[1:-1]}
        assert all(length % (16 * period) == 0 for length in lengths)
        assert 16 * period in lengths


def test_noise_period_0_is_period_1() -> None:
    assert noise_bits(0, 300) == noise_bits(1, 300)


def test_the_noise_register_repeats_after_131071_steps() -> None:
    chip = PSG(record=False)
    chip.noise_register = 1
    seen = 0
    while True:
        chip._shift_noise()
        seen += 1
        if chip.noise_register == 1:
            break
    assert seen == 2**17 - 1


def test_an_empty_noise_register_takes_in_a_one() -> None:
    chip = PSG(record=False)
    assert chip.noise_register == 0
    chip._shift_noise()
    assert chip.noise_register == 1


# -- the envelope ----------------------------------------------------------------------


def shape_levels(shape: int, top: int, ramps: int = 4) -> list[int]:
    """The levels a shape steps through, from GI's and Yamaha's shape diagrams:
    one ramp, then nothing, a held level, or more ramps."""
    down, up = list(range(top, -1, -1)), list(range(top + 1))
    rising = bool(shape & 4)
    out = list(up if rising else down)
    for _ in range(ramps - 1):
        if not shape & 8:
            out += [0] * (top + 1)
        elif shape & 1:
            out += [top if rising ^ bool(shape & 2) else 0] * (top + 1)
        else:
            if shape & 2:
                rising = not rising
            out += up if rising else down
    return out


def envelope_levels(variant, shape: int, period: int = 1, steps: int = 0) -> list[int]:
    """The envelope's level at each of its steps after a shape write."""
    chip = PSG(variant)
    chip.write_register(7, 0x3F)
    chip.write_register(8, 0x10)
    chip.write_register(11, period)
    divider = variant.clock_divider
    chip.run(8 * 16 * divider)  # the start of the divider's eight: the counter is held
    chip.take_outputs()
    chip.write_register(13, shape)
    step = 8 * max(period, 1) * (2 if variant.envelope_steps == 16 else 1) * divider
    chip.run(step * steps)
    return [a for a, _, _ in chip.take_outputs()[step // 2 :: step]]


@pytest.mark.parametrize("shape", range(16))
@pytest.mark.parametrize("variant", [AY8910, YM2149, SUNSOFT_5B], ids=lambda v: v.name)
def test_every_envelope_shape(variant, shape: int) -> None:
    top = variant.envelope_steps - 1
    expected = shape_levels(shape, top)
    assert envelope_levels(variant, shape, steps=len(expected)) == expected


def test_an_ay_envelope_steps_every_sixteen_clocks_a_count() -> None:
    for period in (1, 3, 10):
        assert envelope_levels(AY8910, 0x08, period, 40) == shape_levels(0x08, 15)[:40]


def test_a_yamaha_envelope_has_twice_the_steps_at_twice_the_rate() -> None:
    for period in (1, 3):
        ay = envelope_levels(AY8910, 0x0E, period, 64)
        ym = envelope_levels(YM2149, 0x0E, period, 128)
        assert [level >> 1 for level in ym[1::2]] == ay


def test_envelope_period_0_is_period_1() -> None:
    for variant in (AY8910, YM2149):
        zero = envelope_levels(variant, 0x0A, 0, 100)
        assert zero == envelope_levels(variant, 0x0A, 1, 100)


def test_writing_the_shape_restarts_the_envelope_whatever_the_value() -> None:
    chip = PSG()
    chip.write_register(7, 0x3F)
    chip.write_register(8, 0x10)
    chip.write_register(11, 1)
    chip.write_register(13, 0x08)
    chip.run(16 * 7)
    assert chip.levels()[0] < 15
    chip.write_register(13, 0x08)
    assert chip.levels()[0] == 15


def first_step_after_restart(phase: int, odd_count: bool, period: int = 4) -> int:
    """Clocks from a shape write on ``phase`` of the divider, the period counter
    odd or even, to the first step."""
    chip = PSG()
    chip.write_register(7, 0x3F)
    chip.write_register(8, 0x10)
    chip.write_register(11, period)
    chip.write_register(12, 1)  # a long period while the counter is set up
    chip.run(8 * 9 + phase)
    assert chip.phase == phase and not chip.envelope_held
    chip.envelope_count = 7 if odd_count else 6
    chip.write_register(12, 0)
    chip.take_outputs()
    chip.write_register(13, 0x08)
    return channel_a(chip, 8 * max(period, 1) * 4 + 16).index(14)


def test_a_restart_in_the_first_half_clears_the_counter_and_holds_it() -> None:
    # Cleared and held until the count on phase 3; then 4 counts and a strobe to
    # expire once, and the same again for the step.
    for phase in (0, 1, 2, 3):
        to_count = (COUNT_PHASE - phase) % 8
        for odd in (False, True):
            assert first_step_after_restart(phase, odd) == to_count + 8 * 8 - 1


def test_a_restart_in_the_second_half_leaves_the_counters_lowest_bit() -> None:
    for phase in (4, 5, 6, 7):
        to_count = (COUNT_PHASE - phase) % 8
        even = first_step_after_restart(phase, False)
        odd = first_step_after_restart(phase, True)
        assert even == to_count + 8 * 8 - 1  # restarted from 0
        assert odd == even - 8  # restarted from 1: a count sooner


def test_a_counter_restarted_at_0_in_the_second_half_can_expire_at_0() -> None:
    # Period 0: nothing holds the counter, and 0 >= 0 at the very next strobe.
    late = first_step_after_restart(5, False, period=0)
    early = first_step_after_restart(1, False, period=0)
    assert late == (STROBE_PHASE - 5) % 8 + 8
    assert early == (STROBE_PHASE - 1) % 8 + 16


# -- the mixer and the codes -----------------------------------------------------------


@pytest.mark.parametrize("mixer", range(64))
def test_the_mixer_is_tone_or_disabled_and_noise_or_disabled(mixer: int) -> None:
    chip = PSG(record=False)
    for channel in range(3):
        chip.write_register(8 + channel, 15)
    chip.write_register(7, mixer)
    for tones in range(8):
        for noise_bit in (0, 1):
            chip.tone_output = [tones >> channel & 1 for channel in range(3)]
            chip.noise_register = 0 if noise_bit else 0x10000  # heard inverted
            chip.write_register(7, mixer)
            for channel in range(3):
                tone = (tones >> channel & 1) | (mixer >> channel & 1)
                noise = noise_bit | (mixer >> (channel + 3) & 1)
                assert chip.levels()[channel] == (15 if tone and noise else 0)


def test_an_ay_drives_its_volume_and_a_yamaha_part_twice_it_and_one() -> None:
    for variant, code in ((AY8910, lambda v: v), (YM2149, lambda v: 2 * v + 1)):
        chip = PSG(variant)
        chip.write_register(7, 0x3F)
        for volume in range(16):
            chip.write_register(9, volume)
            assert chip.levels() == (0 if variant is AY8910 else 1, code(volume), code(0))


def test_volume_bit_4_gives_the_channel_to_the_envelope() -> None:
    chip = PSG()
    chip.write_register(7, 0x3F)
    chip.write_register(13, 0x0D)  # rising, then held at the top
    chip.write_register(10, 0x13)
    chip.run(16 * 5 + 8)
    assert chip.levels() == (0, 0, 5)


def test_mix_adds_the_three_levels_by_the_dac_table() -> None:
    chip = PSG(YM2149)
    chip.write_register(7, 0x3F)
    for channel, volume in enumerate((15, 8, 0)):
        chip.write_register(8 + channel, volume)
    dac = YM2149.dac
    assert chip.mix() == pytest.approx(dac[31] + dac[17] + dac[1])
    chip.run(3)
    assert chip.take_samples() == [pytest.approx(chip.mix())] * 3


# -- the clock divider -----------------------------------------------------------------


def test_the_5b_moves_on_every_second_clock() -> None:
    fast, slow = tone_chip(YM2149, 3), tone_chip(SUNSOFT_5B, 3)
    ym = channel_a(fast, 500)
    assert channel_a(slow, 1000)[1::2] == ym
    assert SUNSOFT_5B.clock_divider == 2 and not SUNSOFT_5B.has_sel_pin


def test_the_ym2149s_sel_pin_halves_its_clock() -> None:
    assert YM2149.has_sel_pin and YM2149.clock_divider == 1
    chip = tone_chip(YM2149, 2)
    chip.clock_divider = 2
    chip.run(64 * 3)
    chip.take_outputs()
    assert {length for _, length in runs(channel_a(chip, 640))[1:-1]} == {32}


# -- the bus ---------------------------------------------------------------------------


def test_an_address_byte_with_high_bits_deselects_the_chip() -> None:
    chip = PSG()
    chip.select(0x08)
    chip.write(12)
    chip.select(0x13)
    assert not chip.selected
    chip.write(3)
    assert chip.read() == 0xFF
    assert chip.address == 8  # the latch kept its register
    chip.select(0x08)
    assert chip.read() == 12


def test_nothing_is_selected_after_reset() -> None:
    chip = PSG()
    chip.write(0x55)
    assert chip.registers == [0] * 16


@pytest.mark.parametrize("variant", VARIANTS.values(), ids=lambda v: v.name)
def test_what_each_register_reads_back(variant) -> None:
    widths = (0xFF, 0x0F, 0xFF, 0x0F, 0xFF, 0x0F, 0x1F, 0xFF, 0x1F, 0x1F, 0x1F, 0xFF, 0xFF, 0x0F)
    chip = PSG(variant)
    for register, width in enumerate(widths):
        chip.write_register(register, 0xFF)
        chip.select(register)
        assert chip.read() == (0xFF if variant.codes == 32 else width)
        assert chip.registers[register] == (0xFF if variant.codes == 32 else width)


def test_the_engine_uses_only_a_registers_own_bits() -> None:
    wide, narrow = PSG(YM2149), PSG(YM2149)
    for register, value in ((7, 0x00), (8, 0x0F), (9, 0x10), (0, 3), (6, 2), (11, 2)):
        wide.write_register(register, value)
        narrow.write_register(register, value)
    for register, extra, value in ((1, 0xF0, 0), (6, 0xE0, 2), (8, 0xE0, 0x0F), (13, 0xF0, 0x0A)):
        wide.write_register(register, extra | value)
        narrow.write_register(register, value)
    wide.run(2000)
    narrow.run(2000)
    assert wide.take_outputs() == narrow.take_outputs()


def test_an_ays_missing_bits_read_as_the_internal_bus_was_left() -> None:
    chip = PSG(AY8910)
    chip.select(1)
    chip.write(0xB7)
    assert chip.read() == 0xB7  # the bus still holds the byte written
    chip.select(1)
    assert chip.read() == 0x07  # an address byte clears it
    assert chip.read_register(1) == 0x07


def test_read_register_leaves_the_latch_alone() -> None:
    chip = PSG()
    chip.write_register(0, 0x12)
    chip.select(2)
    assert chip.read_register(0) == 0x12
    assert chip.address == 2


# -- the ports -------------------------------------------------------------------------


def test_an_input_port_reads_the_outside_and_pull_ups_without_one() -> None:
    chip = PSG()
    assert chip.read_register(14) == 0xFF
    chip.port_a_in = lambda: 0x5A
    chip.port_b_in = lambda: 0xC3
    assert (chip.read_register(14), chip.read_register(15)) == (0x5A, 0xC3)


def test_an_output_port_drives_its_latch_and_reads_its_pins() -> None:
    driven: dict[str, int] = {}
    chip = PSG()
    chip.port_a_out = lambda value: driven.__setitem__("a", value)
    chip.port_b_out = lambda value: driven.__setitem__("b", value)
    chip.write_register(14, 0x12)
    assert driven == {}  # an input drives nothing new
    chip.write_register(7, 0x40)
    assert driven == {"a": 0x12}  # told of a change, and only of a change
    chip.write_register(14, 0x34)
    chip.write_register(15, 0x56)
    chip.write_register(7, 0xC0)
    assert driven == {"a": 0x34, "b": 0x56}
    assert chip.read_register(14) == 0x34
    chip.port_a_in = lambda: 0xF0  # the outside pulls four pins low
    assert chip.read_register(14) == 0x30
    chip.write_register(7, 0x00)
    assert driven == {"a": 0xFF, "b": 0xFF}


def test_a_port_that_is_not_bonded_out_sees_only_its_pull_ups() -> None:
    for variant, bonded in ((AY8912, "A"), (AY8913, ""), (SUNSOFT_5B, "")):
        chip = PSG(variant)
        called: list[int] = []
        chip.port_a_in = chip.port_b_in = lambda: 0x00
        chip.port_a_out = chip.port_b_out = called.append
        assert chip.read_register(14) == (0x00 if "A" in bonded else 0xFF)
        assert chip.read_register(15) == 0xFF
        chip.write_register(15, 0x21)
        chip.write_register(7, 0x80)
        assert chip.read_register(15) == 0x21  # the latch is there all the same
        chip.write_register(14, 0x43)
        chip.write_register(7, 0xC0)
        assert called == ([0x43] if "A" in bonded else [])


# -- reset -----------------------------------------------------------------------------


def test_reset_is_power_on() -> None:
    chip = tone_chip(period=3)
    chip.write_register(13, 0x0E)
    chip.write_register(6, 4)
    chip.run(12345)
    chip.reset()
    fresh = PSG()
    assert chip.clock == 0 and chip.take_outputs() == []
    for used, new in ((chip, fresh),):
        used.write_register(7, 0x00)
        new.write_register(7, 0x00)
        for register in (8, 9, 10):
            used.write_register(register, 0x10 if register == 9 else 15)
            new.write_register(register, 0x10 if register == 9 else 15)
    chip.run(5000)
    fresh.run(5000)
    assert chip.take_outputs() == fresh.take_outputs()
