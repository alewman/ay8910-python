# SPDX-License-Identifier: MIT
"""The parts built around the PSG engine, and their DAC curves.

What differs between General Instrument's AY-3-8910, 8912 and 8913, Yamaha's
YM2149 and the sound half of Sunsoft's 5B is data on a :class:`PSGVariant`, not
branches through the engine: how many envelope steps, which port pins are bonded
out, what a register reads back, whether the clock can be halved, and the DAC.

A DAC table maps the chip's digital output, the *code* a channel drives, to a
level from 0.0 to 1.0. The AY parts have sixteen codes (the 4-bit volume; 0 turns
the channel's output transistors off); the Yamaha parts have thirty-two (the 5-bit
envelope; a 4-bit volume ``v`` drives code ``2v + 1``). The tables are measurements
or the manufacturers' figures, each cited where it is defined, and docs/claims.md
says how strongly each is known. The analogue path after the pins (the load the
three outputs share, the board's filters and amplifier) belongs to the board.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The bits each register has a use for (GI's data sheet, "Register array"). The
#: AY's latches are exactly these widths: read after an address byte, the other
#: bits are 0 on a real AY-3-8910 (MAME ay8910.cpp, BSD-3-Clause, "Tested and
#: confirmed on hardware") and at the die model's pins (docs/rederived.md, item 3).
REGISTER_WIDTH_MASKS = (
    0xFF, 0x0F, 0xFF, 0x0F, 0xFF, 0x0F, 0x1F, 0xFF,
    0x1F, 0x1F, 0x1F, 0xFF, 0xFF, 0x0F, 0xFF, 0xFF,
)  # fmt: skip

#: A part whose registers keep every bit written, used or not.
ALL_BITS = (0xFF,) * 16


def _normalised(volts: tuple[float, ...]) -> tuple[float, ...]:
    low, high = volts[0], volts[-1]
    return tuple((v - low) / (high - low) for v in volts)


#: The AY-3-8910's sixteen levels, measured: Matthew Westcott's voltages on a ZX
#: Spectrum 128's channel C pin for each fixed volume (comp.sys.sinclair, December
#: 2001, placed in the public domain by him; quoted in MAME's ay8910.cpp, lines
#: 681-716), with the level-0 voltage taken as silence and level 15 as 1.0.
DAC_AY_MEASURED = _normalised(
    (1.147, 1.162, 1.169, 1.178, 1.192, 1.213, 1.238, 1.299,
     1.336, 1.457, 1.573, 1.707, 1.882, 2.060, 2.320, 2.580)
)  # fmt: skip

#: The AY-3-8910's levels as a plain logarithmic ladder: each step down divides
#: the voltage by the square root of two (3 dB), and level 0 is off. GI's data
#: sheet says only that "the D/A conversion is performed in logarithmic steps with
#: a normalized voltage range of from 0 to 1 Volt" and draws the curve without
#: numbers (Fig. 3); the square root of two is Yamaha's figure for the same sixteen
#: volumes (below), and the measurements run about 2.8 dB a step on average.
DAC_AY_LOGARITHMIC = (0.0, *(2.0 ** ((code - 15) / 2) for code in range(1, 16)))

#: The YM2149's thirty-two levels as Yamaha's catalog draws them (Fig. 1, "Output
#: level of DA convertor": 1 V, .841, .707, .595, .5 ...): each step down divides
#: by the fourth root of two, 1.505 dB, so a volume step is the AY's 3 dB. Codes 0
#: and 1 are both silence here: a volume of 0 drives code 1, and "volume 0 is
#: completely silent" on the 5B's hardware (Sunsoft_5B_audio.wiki, "Tone"). The
#: YM2203's die model, run as a closed box, agrees: one 32-step ramp shows 31
#: levels, the lowest 0, and volume 0 drives it (scripts/ssg_referee.py,
#: ``die_levels``).
DAC_YM_DATASHEET = (0.0, 0.0, *(2.0 ** ((code - 31) / 4) for code in range(2, 32)))

#: The YM2149's levels, measured: the table of Peter Sovietov's ayumi (ayumi.c
#: ``YM_dac_table``, MIT), taken from a real chip. The table is ayumi's, under
#: its licence:
#:
#:   The MIT License
#:
#:   Copyright (c) Peter Sovietov, http://sovietov.com
#:
#:   Permission is hereby granted, free of charge, to any person obtaining a copy
#:   of this software and associated documentation files (the "Software"), to deal
#:   in the Software without restriction, including without limitation the rights
#:   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#:   copies of the Software, and to permit persons to whom the Software is
#:   furnished to do so, subject to the following conditions:
#:
#:   The above copyright notice and this permission notice shall be included in
#:   all copies or substantial portions of the Software.
#:
#:   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#:   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#:   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#:   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#:   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#:   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
#:   THE SOFTWARE.
DAC_YM_MEASURED = (
    0.0, 0.0,
    0.00465400167849, 0.00772106507973, 0.0109559777218, 0.0139620050355,
    0.0169985503929, 0.0200198367285, 0.024368657969, 0.029694056611,
    0.0350652323186, 0.0403906309606, 0.0485389486534, 0.0583352407111,
    0.0680552376593, 0.0777752346075, 0.0925154497597, 0.111085679408,
    0.129747463188, 0.148485542077, 0.17666895552, 0.211551079576,
    0.246387426566, 0.281101701381, 0.333730067903, 0.400427252613,
    0.467383840696, 0.53443198291, 0.635172045472, 0.75800717174,
    0.879926756695, 1.0,
)  # fmt: skip

#: The Sunsoft 5B's levels: a logarithmic DAC of 1.5 dB a step with codes 0 and 1
#: silent, as rainwarrior measured on the cartridge (Sunsoft_5B_audio.wiki,
#: "Envelope" and "Output"): Yamaha's ladder. The 5B's amplifier after it, which
#: compresses above volume 14, is the board's.
DAC_5B = DAC_YM_DATASHEET


@dataclass(frozen=True)
class PSGVariant:
    """What differs between the parts.

    ``envelope_steps``: 16 on the AY parts (a 4-bit envelope counter clocked every
    second time the period counter expires), 32 on Yamaha's (a 5-bit counter
    clocked every time), so a ramp lasts the same and has twice the steps.

    ``ports``: which I/O ports reach pins: "AB" (AY-3-8910, YM2149), "A"
    (AY-3-8912) or "" (AY-3-8913, the 5B). Registers 14 and 15 exist on every part;
    a port that is not bonded out sees only its own pull-ups.

    ``register_masks``: what each register keeps of a byte written, and so what
    a read returns. The AY parts' latches are only as wide as the register, and
    the missing bits read 0 after an address byte (MAME ay8910.cpp, BSD-3-Clause,
    the comment over its read masks: "Tested and confirmed on hardware"; and the
    die model's pins, docs/rederived.md, item 3); the YM2149 keeps and returns
    all eight (the same comment: "YM2149: no anomaly").

    ``clock_divider``: input clocks per internal clock. 1 on the AY parts. The
    YM2149 has a pin for it (/SEL: high 1, low 2), so there it is only the pin's
    level at power-on and :attr:`PSG.clock_divider` may be changed. The 5B is a
    YM2149 with /SEL low for good: 2.

    ``dac``: the level of each code, 0.0 to 1.0, one entry per code (16 or 32).
    """

    name: str
    envelope_steps: int = 16
    ports: str = "AB"
    register_masks: tuple[int, ...] = REGISTER_WIDTH_MASKS
    clock_divider: int = 1
    has_sel_pin: bool = False
    dac: tuple[float, ...] = DAC_AY_MEASURED

    @property
    def codes(self) -> int:
        """How many DAC codes a channel can drive: 16 or 32."""
        return len(self.dac)


#: General Instrument's 40-pin part: two I/O ports.
AY8910 = PSGVariant("AY-3-8910")
#: The same die in 28 pins: port A only.
AY8912 = PSGVariant("AY-3-8912", ports="A")
#: The same die in 24 pins: no ports, BC2 tied high inside.
AY8913 = PSGVariant("AY-3-8913", ports="")
#: Yamaha's SSG: a 32-step envelope, the /SEL pin, every register bit readable.
YM2149 = PSGVariant(
    "YM2149", envelope_steps=32, register_masks=ALL_BITS, has_sel_pin=True, dac=DAC_YM_MEASURED
)
#: The sound of Sunsoft's 5B mapper (Gimmick!): a YM2149 run with its clock halved,
#: no ports, and nothing to read it with.
SUNSOFT_5B = PSGVariant(
    "Sunsoft 5B", envelope_steps=32, ports="", register_masks=ALL_BITS, clock_divider=2, dac=DAC_5B
)

VARIANTS = {v.name: v for v in (AY8910, AY8912, AY8913, YM2149, SUNSOFT_5B)}
