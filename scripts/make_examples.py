#!/usr/bin/env python
"""Make the conformance examples: short manifests and this core's traces of them.

    python scripts/make_examples.py            # write examples/conformance/
    python scripts/make_examples.py --check    # only check they are what is committed
    python scripts/make_examples.py --judge    # and put each to the die model first

With ``--judge`` (the referee built, validation/build_referees.sh) an example the
die disagrees with is not written. The AY-3-8910's are judged whole: codes, port
pins and reads. The other parts' are judged on their codes as scripts/referee.py
judges them (a Yamaha part's halved). Two are this core's word alone:
``sel-pin-ym2149`` moves the /SEL pin, which the AY's die does not have, and
``port-contention-ay-3-8910`` has the outside pull an output port's pins low,
which the die model answers with X.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

from streams import PINS_A, PINS_B, READ, READ_DATA, RESET, SELECT, WRITE, WRITE_DATA, Writer

from ay8910_python import VARIANTS
from ay8910_python.conformance import Event, Manifest, trace_manifest

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "examples" / "conformance"

KIND_NAMES = {
    WRITE: "write",
    READ: "read",
    SELECT: "select",
    WRITE_DATA: "data",
    READ_DATA: "read_data",
    RESET: "reset",
    PINS_A: "pins_a",
    PINS_B: "pins_b",
}
DIVIDER = 100  # a kind of this script's own: the /SEL pin


def tones() -> Writer:
    """Periods 0 to 7 on the three channels, each changed at its own phase of the
    divider, and one period shortened under a running count."""
    w = Writer()
    w.write(7, 0x38)
    for channel, volume in enumerate((15, 9, 4)):
        w.write(8 + channel, volume)
    for period in range(8):
        for channel in range(3):
            w.tone(channel, period + channel)
            w.wait(1 + channel)
        w.wait(max(period, 2) * 8 * 4 + period)
    w.tone(0, 40)
    w.wait(8 * 25 + 3)
    for step in range(8):  # the open strobe: a shorter period written on each phase
        w.tone(0, 40)
        w.wait(8 * 30 + step)
        w.tone(0, 5)
        w.wait(8 * 12 - step)
    return w


def noise() -> Writer:
    """Noise periods 0, 1, 2 and 5, alone on A and gating a tone on B."""
    w = Writer()
    w.write(8, 15)
    w.write(9, 11)
    w.tone(1, 9)
    w.write(7, 0x2E)
    for period in (0, 1, 2, 5):
        w.write(6, period)
        w.wait(max(period, 1) * 16 * 60 + period)
    return w


def envelope_shapes() -> Writer:
    """All sixteen shapes at period 1, each through three ramps."""
    w = Writer()
    w.write(7, 0x3F)
    w.write(8, 0x10)
    w.write(9, 0x1F)
    w.write(10, 0x0B)
    for shape in range(16):
        w.envelope(1, shape)
        w.wait(16 * 16 * 3 + 8 + shape)
    return w


def envelope_restarts() -> Writer:
    """The shape register rewritten on every phase of the divider under counts
    both odd and even, at periods 0 to 3: the restarted counter's first step."""
    w = Writer()
    w.write(7, 0x3F)
    w.write(8, 0x10)
    for period in range(4):
        w.envelope(period, 0x0C)
        w.wait(100)
        for phase in range(16):
            w.write(13, 0x0C if phase % 2 else 0x0E)
            w.wait(max(period, 1) * 16 * 3 + 8 + phase)
    return w


def mixer() -> Writer:
    """Every mixer value over a tone, the noise and an envelope."""
    w = Writer()
    w.tone(0, 3)
    w.tone(1, 5)
    w.tone(2, 11)
    w.write(6, 2)
    w.envelope(3, 0x0E)
    for channel, volume in enumerate((15, 0x10, 7)):
        w.write(8 + channel, volume)
    for value in range(64):
        w.write(7, value)
        w.wait(101)
    return w


def registers() -> Writer:
    """Every register written and read back; a read straight after a write with
    no address byte between; address bytes that deselect the chip."""
    w = Writer()
    w.write(7, 0xC0)
    for value in (0xFF, 0x00, 0xA5):
        for register in range(16):
            w.write(register, value | 0xC0 if register == 7 else value, wait=3)
            w.read(register, wait=5)
    w.write(1, 0xB7, wait=2)
    w.event(READ_DATA, wait=2)  # the bus still holds $B7: an AY returns all of it
    w.read(1, wait=2)  # the address byte cleared the bus: $07
    w.event(SELECT, 0x18, wait=2)  # high bits set: deselected
    w.event(WRITE_DATA, 0, 0x55, wait=2)
    w.event(READ_DATA, wait=2)
    w.read(8, wait=2)
    w.write(8, 12, wait=2)
    w.event(SELECT, 0xF8, wait=2)
    w.event(WRITE_DATA, 0, 3, wait=2)
    w.read(8, wait=2)
    return w


def ports() -> Writer:
    """Both ports read as inputs with the outside driving them, then written as
    outputs, the direction bits taken one at a time."""
    w = Writer()
    for pins in (0x00, 0x5A, 0xFF):
        w.event(PINS_A, pins, wait=1)
        w.event(PINS_B, pins ^ 0xFF, wait=1)
        w.read(14, wait=2)
        w.read(15, wait=2)
    w.event(PINS_A, 0xFF, wait=1)
    w.event(PINS_B, 0xFF, wait=1)
    for direction in (0x40, 0x80, 0xC0, 0x00, 0xC0):
        w.write(7, direction | 0x3F, wait=2)
        for value in (0x12, 0xED):
            w.write(14, value, wait=2)
            w.write(15, value ^ 0x0F, wait=2)
            w.read(14, wait=2)
            w.read(15, wait=2)
    return w


def reset() -> Writer:
    """/RESET in the middle of sound, on each phase of the divider."""
    w = Writer()
    for phase in range(8):
        w.write(7, 0x30)
        w.write(8, 15)
        w.write(9, 0x10)
        w.write(10, 9)
        w.tone(0, 3)
        w.tone(2, 2)
        w.write(6, 1)
        w.envelope(2, 0x0A)
        w.wait(400 + phase)
        w.event(RESET)
        w.wait(40)
    return w


def sunsoft_5b() -> Writer:
    """The 5B as Gimmick! uses it and as it does not: three tones at every
    volume, then the noise and both envelope directions. Clocks are the CPU's;
    events land on even ones."""
    w = Writer()
    w.write(7, 0x38)
    w.tone(0, 2)
    w.tone(1, 3)
    w.tone(2, 5)
    for volume in range(16):
        for channel in range(3):
            w.write(8 + channel, (volume + channel * 5) & 15)
        w.wait(16 * 20)
    w.write(6, 1)
    w.write(7, 0x1C)
    w.wait(16 * 2 * 40)
    w.write(7, 0x3F)
    for channel in range(3):
        w.write(8 + channel, 0x10)
    for shape in (0x0E, 0x08, 0x0B):
        w.envelope(1, shape)
        w.wait(16 * 32 * 3 + 10)
    return w


def sel_pin() -> Writer:
    """The YM2149's /SEL pin taken low and high again under a tone and an
    envelope."""
    w = Writer()
    w.write(7, 0x3E)
    w.write(8, 15)
    w.write(9, 0x10)
    w.tone(0, 3)
    w.envelope(1, 0x0E)
    for divider in (2, 1, 2, 1):
        w.wait(8 * 3 * 9 + 5)
        w.event(DIVIDER, divider)
    w.wait(300)
    return w


def unused_bits() -> Writer:
    """A Yamaha part keeps every bit written, but its sound uses only the bits a
    register has a use for: the high bits of the coarse periods, the noise
    period, the volumes and the shape, written under running sound."""
    w = Writer()
    w.write(7, 0x00)
    w.write(8, 15)
    w.write(9, 0x10)
    w.write(10, 9)
    w.tone(0, 3)
    w.tone(1, 5)
    w.write(6, 2)
    w.envelope(2, 0x0A)
    w.wait(400)
    for register, value in ((1, 0xF0), (3, 0xA0), (6, 0xE2), (8, 0xEF), (10, 0xC9), (13, 0xFA)):
        w.write(register, value)
        w.wait(403)
        w.read(register, wait=1)
    return w


def port_contention() -> Writer:
    """An output port whose pins the outside pulls low: a read returns the pins,
    the latch ANDed with the outside (docs/claims.md: this core's reading of the
    pin; the die model drives it both ways and has no answer)."""
    w = Writer()
    w.write(7, 0xFF)
    w.write(14, 0xF5)
    w.write(15, 0x3C)
    for pins in (0xFF, 0x0F, 0xA0):
        w.event(PINS_A, pins, wait=1)
        w.event(PINS_B, pins ^ 0xFF, wait=1)
        w.read(14, wait=2)
        w.read(15, wait=2)
    return w


def random_walk(seed: int, step: int = 1) -> Writer:
    """Seeded writes to every register at seeded times."""
    rng = random.Random(seed)
    w = Writer()
    for _ in range(260):
        register = rng.randrange(14)
        if register in (1, 3, 5, 12):
            value = rng.choice((0, 0, 0, 1))
        elif register in (0, 2, 4, 6, 11):
            value = rng.randrange(9)
        else:
            value = rng.randrange(256)
        w.write(register, value)
        w.wait(rng.choice((0, 1, 2, 3, 7, 8, 9, 31, 64, 130)) * step)
    return w


#: The examples the die model has no say on (the /SEL pin; a port's pins fought over).
NOT_JUDGED = {"sel-pin-ym2149", "port-contention-ay-3-8910"}

#: name -> (variant, writer)
EXAMPLES = {
    "tones-ay-3-8910": ("AY-3-8910", tones),
    "noise-ay-3-8910": ("AY-3-8910", noise),
    "envelope-shapes-ay-3-8910": ("AY-3-8910", envelope_shapes),
    "envelope-shapes-ym2149": ("YM2149", envelope_shapes),
    "envelope-restarts-ay-3-8910": ("AY-3-8910", envelope_restarts),
    "mixer-ay-3-8910": ("AY-3-8910", mixer),
    "registers-ay-3-8910": ("AY-3-8910", registers),
    "registers-ym2149": ("YM2149", registers),
    "ports-ay-3-8910": ("AY-3-8910", ports),
    "ports-ay-3-8912": ("AY-3-8912", ports),
    "ports-ay-3-8913": ("AY-3-8913", ports),
    "reset-ay-3-8910": ("AY-3-8910", reset),
    "sunsoft-5b": ("Sunsoft 5B", sunsoft_5b),
    "sel-pin-ym2149": ("YM2149", sel_pin),
    "unused-bits-ym2149": ("YM2149", unused_bits),
    "port-contention-ay-3-8910": ("AY-3-8910", port_contention),
    "random-walk-ay-3-8910": ("AY-3-8910", lambda: random_walk(31)),
    "random-walk-ym2149": ("YM2149", lambda: random_walk(32)),
    "random-walk-sunsoft-5b": ("Sunsoft 5B", lambda: random_walk(33, 2)),
}


def manifest(name: str) -> tuple[Manifest, list[tuple[int, int, int, int]]]:
    """The example's manifest, and its events as the referee's stream. A part that
    halves its clock has its events on even clocks, two to the die's one."""
    variant, make = EXAMPLES[name]
    writer = make()
    scale = VARIANTS[variant].clock_divider
    events, clocks = writer.done(tail=200)
    made = Manifest(
        name=name,
        variant=variant,
        events=tuple(
            Event(t * scale, "divider" if kind == DIVIDER else KIND_NAMES[kind], a, b)
            for t, kind, a, b in events
        ),
        clocks=clocks * scale,
    )
    return made, events


def judged(name: str) -> str | None:
    """What the die says of the example: None if it agrees, else where it does not."""
    from referee import compare

    made, events = manifest(name)
    if name in NOT_JUDGED:
        return None
    return compare(
        VARIANTS[made.variant], events, made.clocks // VARIANTS[made.variant].clock_divider
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="check, do not write")
    parser.add_argument("--judge", action="store_true", help="put each to the die model first")
    args = parser.parse_args(argv)
    bad = 0
    for name in EXAMPLES:
        made, _ = manifest(name)
        if args.judge:
            difference = judged(name)
            if difference is not None:
                print(f"{name}: the die disagrees at {difference}; not written")
                bad += 1
                continue
        files = {
            OUT / f"{name}.json": made.to_json(),
            OUT / f"{name}.trace": "".join(line + "\n" for line in trace_manifest(made)),
        }
        for path, text in files.items():
            if args.check:
                if not path.exists() or path.read_text(encoding="utf-8") != text:
                    print(f"{path.name}: not what this script makes")
                    bad += 1
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
        lines = files[OUT / f"{name}.trace"].count("\n")
        print(f"{name}: {len(made.events)} events, {made.clocks:,} clocks, {lines} trace lines")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
