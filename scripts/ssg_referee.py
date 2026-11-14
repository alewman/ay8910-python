#!/usr/bin/env python
"""Compare the Yamaha parts' waveforms with the SSG of the YM2203's die, step by step.

    python scripts/ssg_referee.py              # every case, YM2149 and Sunsoft 5B
    python scripts/ssg_referee.py --restarts   # where the two dies part: the table

No die-derived model of the YM2149 itself is published. The nearest silicon is the
SSG block inside Yamaha's YM2203, which nukeykt transcribed from its die
(YM2203-LLE, driven by validation/ssg_ref.c). It is the same programmer's model as
the YM2149 with the 32-step envelope, but it is not the AY's machine: it serves
the three tones and the envelope in turn from one shared counter, so *when* inside
a step a write takes hold differs per register, and it cannot be compared with
this core clock for clock.

What can be compared is what each register setting *sounds*: for every case
below the registers are written, both sides are left to run, and each channel's
output is reduced to its runs, ``(level, steps)`` (a step is the chip's count:
eight internal clocks). The first and last run of a window are cut short by its
edges and are dropped; the rest must be equal run for run. That judges every tone
and noise period (0 as 1 included), the noise register's sequence, all sixteen
envelope shapes with all thirty-two levels and their rate, the volume-to-level
rule ``2v + 1`` and the mixer's gates (a channel given tone and noise together
is left out: that waveform depends on how the two are aligned), on Yamaha's own
silicon. It does not judge what
happens in the step a register is written: :func:`restarts` measures the one case
of that with a musical consequence, the envelope's restart, where the dies differ.
"""

from __future__ import annotations

import argparse
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from ay8910_python import CLOCKS_PER_STEP, PSG, SUNSOFT_5B, YM2149, PSGVariant

ROOT = Path(__file__).resolve().parent.parent
REFEREE = ROOT / "reference" / "build-referees" / "ssg_ref"

#: (step, register, value), at most one to a step.
Write = tuple[int, int, int]
Runs = list[tuple[int, int]]


class Case:
    """Writes, one per step from step 0, then a window to watch from ``settle``
    steps after the last of them."""

    def __init__(self, name: str, writes: list[tuple[int, int]], settle: int, watch: int) -> None:
        self.name = name
        self.writes = writes
        self.settle = settle
        self.watch = watch


def cases() -> list[Case]:
    made = []
    for period in (*range(13), 100, 0xFFF):
        writes = [(7, 0x38), (8, 15), (9, 8), (10, 1)]
        for channel in range(3):
            value = min(period + channel, 0xFFF)
            writes += [(channel * 2, value & 0xFF), (channel * 2 + 1, value >> 8)]
        made.append(Case(f"tone period {period}", writes, 3 * period + 20, 14 * max(period, 4)))
    for period in range(32):
        writes = [(7, 0x37), (8, 15), (6, period)]
        made.append(Case(f"noise period {period}", writes, 40, 2 * max(period, 1) * 700))
    for period in (0, 1, 2, 5):
        for shape in range(16):
            writes = [(7, 0x3F), (8, 0x10), (9, 0x10), (11, period), (12, 0), (13, shape)]
            made.append(
                Case(f"envelope shape {shape} period {period}", writes, 0, 32 * max(period, 1) * 5)
            )
    made.append(
        Case(
            "envelope period 300",
            [(7, 0x3F), (8, 0x10), (11, 300 & 0xFF), (12, 300 >> 8), (13, 14)],
            0,
            300 * 70,
        )
    )
    for volume in range(32):
        writes = [(7, 0x3F), (8, volume), (9, volume ^ 0x0F), (11, 3), (13, 12)]
        made.append(Case(f"volume {volume}", writes, 4, 32 * 3 * 3))
    for mixer in range(64):
        writes = [(0, 3), (2, 5), (4, 7), (6, 2), (8, 15), (9, 11), (10, 6), (7, mixer)]
        made.append(Case(f"mixer {mixer}", writes, 30, 900))
    return made  # fmt: skip


def die(writes: list[Write], steps: int) -> list[tuple[float, float, float]]:
    with tempfile.TemporaryDirectory() as tmp:
        events, out = Path(tmp) / "events.bin", Path(tmp) / "out.bin"
        events.write_bytes(b"".join(struct.pack("<QBB", *write) for write in writes))
        subprocess.run([str(REFEREE), str(events), str(out), str(steps), "0"], check=True)
        return list(struct.iter_unpack("<fff", out.read_bytes()))


def die_levels() -> dict[float, int]:
    """The model's 31 output levels, in order, learnt from one envelope ramp: its
    DAC table has 32 entries of which the lowest two are both 0."""
    ramp = die([(0, 7, 0x3F), (1, 8, 0x10), (2, 11, 1), (3, 13, 0x0E)], 400)
    levels = sorted({a for a, _, _ in ramp})
    if len(levels) != 31:
        raise RuntimeError(f"expected 31 levels from the die's ramp, saw {len(levels)}")
    return {level: rank for rank, level in enumerate(levels)}


def core(variant: PSGVariant, writes: list[Write], steps: int) -> list[tuple[int, int, int]]:
    """The core's three codes at the end of each step, as the die's ranks: codes 0
    and 1 are the same level. Writes land half way through a step, after the
    count."""
    chip = PSG(variant, record=False)
    clocks = CLOCKS_PER_STEP * variant.clock_divider
    chip.run(clocks // 2)
    pending = iter(writes)
    write = next(pending, None)
    out = []
    for step in range(steps):
        while write is not None and write[0] <= step:
            chip.write_register(write[1], write[2])
            write = next(pending, None)
        chip.run(clocks)
        out.append(tuple(max(code - 1, 0) for code in chip.levels()))
    return out


def runs(levels: list[int]) -> Runs:
    """A channel's output as (level, steps) runs, without the first and the last,
    which the window's edges cut short."""
    found: Runs = []
    for level in levels:
        if found and found[-1][0] == level:
            found[-1] = (level, found[-1][1] + 1)
        else:
            found.append((level, 1))
    return found[1:-1]


def same_waveform(ours: Runs, theirs: Runs) -> bool:
    """Equal run for run, allowing either side to have begun up to three runs
    into the other (the two chips do not take a write in the same step)."""
    if not ours and not theirs:
        return True
    for skip_ours in range(4):
        for skip_theirs in range(4):
            a, b = ours[skip_ours:], theirs[skip_theirs:]
            length = min(len(a), len(b))
            if length >= max(len(ours), len(theirs)) - 6 and a[:length] == b[:length]:
                return True
    return False


def compare(variant: PSGVariant, case: Case, ranks: dict[float, int]) -> tuple[int, str | None]:
    """The steps watched, and which channel's waveform differs, or None."""
    writes = [(step, register, value) for step, (register, value) in enumerate(case.writes)]
    start = len(writes) + case.settle
    steps = start + case.watch
    theirs = [tuple(ranks[level] for level in sample) for sample in die(writes, steps)]
    ours = core(variant, writes, steps)
    mixer = next((value for register, value in reversed(case.writes) if register == 7), 0)
    for channel, name in enumerate("ABC"):
        if not mixer >> channel & 1 and not mixer >> (channel + 3) & 1:
            # Tone AND noise: the waveform depends on how the two happen to be
            # aligned, which is each chip's own business. Not judged.
            continue
        a = runs([sample[channel] for sample in ours[start:]])
        b = runs([sample[channel] for sample in theirs[start:]])
        if not same_waveform(a, b):
            return case.watch, f"channel {name}: core {a[:6]}..., die {b[:6]}..."
    return case.watch, None


def restarts(variant: PSGVariant, ranks: dict[float, int]) -> None:
    """How long the first step of a restarted envelope lasts, on each die."""
    print("envelope period: steps from the shape write to the first change of level")
    for period in (1, 2, 3, 5, 8):
        ours_all, theirs_all = set(), set()
        for at in range(40, 40 + 2 * period):
            writes = [(0, 7, 0x3F), (1, 8, 0x10), (2, 11, period), (3, 13, 12), (at, 13, 12)]
            steps = at + 4 * period + 8
            theirs = [ranks[sample[0]] for sample in die(writes, steps)]
            ours = [sample[0] for sample in core(variant, writes, steps)]
            for seen, levels in ((ours_all, ours), (theirs_all, theirs)):
                seen.add(next(step for step in range(at, steps) if levels[step] == 1) - at)
        ours, theirs = sorted(ours_all), sorted(theirs_all)
        print(f"  {period:2d}: core (the AY's die) {ours}, the YM2203's die {theirs}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--restarts", action="store_true", help="print the restart table")
    parser.add_argument("--first", action="store_true", help="stop at the first difference")
    args = parser.parse_args(argv)
    ranks = die_levels()
    if args.restarts:
        restarts(YM2149, ranks)
        return 0
    bad = total = 0
    for variant in (YM2149, SUNSOFT_5B):
        steps = different = 0
        for case in cases():
            watched, difference = compare(variant, case, ranks)
            steps += watched
            if difference is not None:
                different += 1
                print(f"{variant.name:10s} {case.name}: DIFFER, {difference}", flush=True)
                if args.first:
                    return 1
        print(
            f"{variant.name:10s} {len(cases())} cases, {steps:,} steps watched: {different} differ"
        )
        bad += different
        total += steps
    print(f"{total:,} steps watched, {bad} cases differ")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
