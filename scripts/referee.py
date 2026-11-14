#!/usr/bin/env python
"""Run event streams through the core and the AY-3-8910's die model, clock by clock.

A stream is a sorted list of ``(clock, kind, a, b)`` events; an event is applied
before the input clock it names (validation/ay_tb.v's convention). Both sides
start from /RESET and run ``clocks`` input clocks. Compared at every clock: the
three channels' DAC codes and the sixteen port pins; and, in order, every byte
read. The result is the first clock that differs, or None.

    python scripts/referee.py                  # the synthetic streams of streams.py
    python scripts/referee.py --only envelope_shapes
    python scripts/referee.py --stream validation/streams/gimmick.stream --half-clock

The die is the AY-3-8910's. The other parts are compared with it as far as it can
judge them (:func:`compare`); what Yamaha's own silicon says of the Yamaha parts
is scripts/ssg_referee.py's.
"""

from __future__ import annotations

import argparse
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

from ay8910_python import AY8910, PSG, VARIANTS, PSGVariant

ROOT = Path(__file__).resolve().parent.parent
REFEREE = ROOT / "reference" / "build-referees" / "ay_ref"

#: The event kinds (validation/ay_tb.v).
WRITE, READ, PINS_A, PINS_B, RESET, SELECT, WRITE_DATA, READ_DATA = range(8)

Event = tuple[int, int, int, int]
#: Per clock: channels A, B, C, then port A's and port B's pins.
Sample = tuple[int, int, int, int, int]


def suite_path() -> str | None:
    """Where the oss-cad-suite's programs are, if $OSS_CAD_SUITE says."""
    suite = os.environ.get("OSS_CAD_SUITE")
    return f"{suite}/bin" if suite else None


def vvp() -> str:
    """Icarus Verilog's runtime: in $OSS_CAD_SUITE/bin, or on the PATH."""
    found = shutil.which("vvp", path=suite_path()) or shutil.which("vvp")
    if found is None:
        raise FileNotFoundError("vvp (Icarus Verilog) is not on the PATH; set OSS_CAD_SUITE")
    return found


def die(stream: list[Event], clocks: int, directory: Path) -> tuple[Path, list[int]]:
    """Run the die model (always the AY-3-8910: all its pins). Its per-clock words
    are left in a file in ``directory``, since a long stream's would not fit in
    memory as Python objects; its reads are returned."""
    events, out, reads = (directory / name for name in ("events.hex", "out.bin", "reads.bin"))
    events.write_text(
        "".join(f"{c << 24 | kind << 16 | a << 8 | b:016x}\n" for c, kind, a, b in stream)
    )
    subprocess.run(
        [vvp(), str(REFEREE), f"+events={events}", f"+count={len(stream)}",
         f"+out={out}", f"+reads={reads}", f"+clocks={clocks}"],
        check=True, stdout=subprocess.DEVNULL,
    )  # fmt: skip
    read = reads.read_bytes()
    return out, [word & 255 for word in struct.unpack(f"<{len(read) // 4}I", read)]


def die_samples(out: Path) -> Iterator[Sample]:
    """The die's samples, clock by clock, from its file."""
    with out.open("rb") as handle:
        while chunk := handle.read(4 << 16):
            for (w,) in struct.iter_unpack("<I", chunk):
                yield (w & 15, w >> 4 & 15, w >> 8 & 15, w >> 12 & 255, w >> 20 & 255)


def core(
    variant: PSGVariant,
    stream: list[Event],
    clocks: int,
    reads: list[int],
    native: list[Event] | None = None,
) -> Iterator[Sample]:
    """The core's samples, in the die's terms, with its reads appended to ``reads``.

    The testbench drives a port's pins only while the port is an input; the
    outside is given as $FF while it is an output. A part that halves its clock
    (the 5B) is run two input clocks to the die's one and sampled after the
    second; ``native`` is then the same events timed in its own input clocks (a
    board stream, where a write can land on either of the two), and without it
    each event lands on the first.
    """
    chip = PSG(variant)
    scale = variant.clock_divider
    if native is None:
        native = [(at * scale, kind, a, b) for at, kind, a, b in stream]
    outside = [0xFF, 0xFF]
    chip.port_a_in = lambda: 0xFF if chip.registers[7] & 0x40 else outside[0]
    chip.port_b_in = lambda: 0xFF if chip.registers[7] & 0x80 else outside[1]
    end = clocks * scale

    def read() -> int:
        """A deselected chip leaves the data pins to the testbench's pull-downs."""
        return chip.read() if chip.selected else 0

    position = 0  # input clocks run so far

    def run_to(target: int) -> Iterator[Sample]:
        nonlocal position
        pins = (chip.read_register(14), chip.read_register(15))
        while position < target:
            count = min(target - position, 1 << 16)
            chip.run(count)
            last_of_each = (scale - 1 - position) % scale
            for levels in chip.take_outputs()[last_of_each::scale]:
                yield (*levels, *pins)
            position += count

    for at, kind, a, b in native:
        if at >= end:
            break
        yield from run_to(at)
        if kind == WRITE:
            chip.write_register(a, b)
        elif kind == READ:
            chip.select(a)
            reads.append(read())
        elif kind == PINS_A:
            outside[0] = a
        elif kind == PINS_B:
            outside[1] = a
        elif kind == RESET:
            chip.reset()
        elif kind == SELECT:
            chip.select(a)
        elif kind == WRITE_DATA:
            chip.write(b)
        elif kind == READ_DATA:
            reads.append(read())
    yield from run_to(end)


def compare(
    variant: PSGVariant,
    stream: list[Event],
    clocks: int,
    judged: tuple[Path, list[int]] | None = None,
    native: list[Event] | None = None,
) -> str | None:
    """Where the core and the die first differ, in words, or None.

    The die is the AY-3-8910, so that part is compared whole: the three codes,
    both ports' pins and every read. The other parts are compared on the codes
    alone. A Yamaha part's thirty-two codes are halved to the AY's sixteen: its
    volume ``2v + 1`` and its envelope, twice the steps at twice the rate, both
    come down to the AY's value, so the die judges everything but the
    envelope's lowest bit. ``judged``: the die's result, when already in hand.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out, their_reads = judged or die(stream, clocks, Path(tmp))
        our_reads: list[int] = []
        whole = variant is AY8910
        shift = 1 if variant.codes == 32 else 0
        ours_all = core(variant, stream, clocks, our_reads, native)
        for clock, (ours, theirs) in enumerate(zip(ours_all, die_samples(out), strict=True)):
            if not whole:
                ours = tuple(code >> shift for code in ours[:3])
                theirs = theirs[:3]
            if ours != theirs:
                return f"clock {clock}: core {ours}, die {theirs}"
    if whole and our_reads != their_reads:
        index = next(
            (i for i, (a, b) in enumerate(zip(our_reads, their_reads, strict=False)) if a != b),
            min(len(our_reads), len(their_reads)),
        )
        ours, theirs = our_reads[index : index + 1], their_reads[index : index + 1]
        return f"read {index}: core {ours}, die {theirs}"
    return None


def load(path: Path, half_clock: bool) -> tuple[list[Event], int, list[Event] | None]:
    """A board stream (scripts/export_board_streams.py): {u64 clock; u8 port; u8
    value} records, port 0 an address byte and 1 a data byte. ``half_clock``: the
    board's chip halves its clock (the 5B), which the die does with half as many
    clocks: the board's clock ``n`` is the die's ``n // 2``. Returned with the
    events in the board's own clocks too, for a part that does its own halving."""
    board = [
        (clock, WRITE_DATA, 0, value) if port else (clock, SELECT, value, 0)
        for clock, port, value in struct.iter_unpack("<QBB", path.read_bytes())
    ]
    if not half_clock:
        return board, (board[-1][0] if board else 0) + 20_000, None
    stream = [(clock >> 1, kind, a, b) for clock, kind, a, b in board]
    return stream, (stream[-1][0] if stream else 0) + 20_000, board


def main(argv: list[str] | None = None) -> int:
    from streams import STREAMS

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only", action="append", help="a stream name to run (repeatable)")
    parser.add_argument("--variant", action="append", help="variant names (default: AY-3-8910)")
    parser.add_argument("--first", action="store_true", help="stop at the first difference")
    parser.add_argument("--stream", type=Path, action="append", help="a board stream file")
    parser.add_argument("--half-clock", action="store_true", help="halve a board stream's clocks")
    parser.add_argument("--clocks", type=int, help="stop after this many clocks")
    args = parser.parse_args(argv)
    variants = [VARIANTS[n] for n in args.variant] if args.variant else [AY8910]
    if args.stream:
        streams = {path.stem: load(path, args.half_clock) for path in args.stream}
    else:
        streams = {name: (*make(), None) for name, make in STREAMS.items()}
    bad = total = 0
    for name, (stream, clocks, board) in streams.items():
        if args.only and name not in args.only:
            continue
        if args.clocks:
            clocks = min(clocks, args.clocks)
        total += clocks
        with tempfile.TemporaryDirectory() as tmp:
            judged = die(stream, clocks, Path(tmp))
            for variant in variants:
                native = board if variant.clock_divider == 2 else None
                first = compare(variant, stream, clocks, judged, native)
                status = "equal" if first is None else f"DIFFER at {first}"
                print(f"{name:26s} {variant.name:10s} {clocks:10,d} clocks: {status}", flush=True)
                bad += first is not None
                if bad and args.first:
                    return 1
    print(f"{total:,} die clocks, {len(variants)} parts: {bad} comparisons differ")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
