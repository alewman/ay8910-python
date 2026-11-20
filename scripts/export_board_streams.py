#!/usr/bin/env python
# SPDX-License-Identifier: MIT
"""Record the 5B's sound-port writes a program makes on famicom-python, as a stream.

    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/path/to/famicom-python/src \\
        python scripts/export_board_streams.py ROM --frames 3600 \\
        --out validation/streams/gimmick.stream

Every CPU write to $C000-$DFFF (the 5B's address byte) and $E000-$FFFF (its data
byte), with the CPU cycle it lands on, whatever the cartridge's mapper: the board
is only watched, through its bus observers, and needs no 5B of its own. The 5B's
sound runs from the CPU's clock (Sunsoft_5B_audio.wiki), one input clock per CPU
cycle, so the CPU cycle is the chip's clock exactly.

Files are {u64 clock; u8 port; u8 value} records (port 0 the address byte, 1 the
data byte), into validation/streams/ (ignored: derived from ROMs). The board is
another repository: run this with bytecode writing off, as above, so that
importing it leaves nothing behind there.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path


def export(rom: Path, frames: int, buttons: dict[int, int]) -> list[tuple[int, int, int]]:
    from famicom_python.machine import MACHINES
    from famicom_python.system import System

    system = System.from_rom(rom, MACHINES["famicom"])
    board = system.board
    ticks = board.cycle_ticks
    writes: list[tuple[int, int, int]] = []

    def observe(kind: str, address: int, value: int, t: int) -> None:
        if kind == "write" and address >= 0xC000:
            writes.append((t // ticks, int(address >= 0xE000), value))

    board.bus_observers.append(observe)
    for frame in range(frames):
        # Each press holds its buttons for six frames.
        board.pads[0].buttons = next(
            (value for start, value in buttons.items() if start <= frame < start + 6), 0
        )
        system.run_frames(1)
    return writes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("rom", type=Path)
    parser.add_argument("--frames", type=int, default=3600)
    parser.add_argument("--press", default="", help="frame:buttons,... each held 6 frames")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    buttons = {int(f): int(b) for f, b in (p.split(":") for p in args.press.split(",") if p)}
    writes = export(args.rom, args.frames, buttons)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(b"".join(struct.pack("<QBB", c, p, v) for c, p, v in writes))
    last = writes[-1][0] if writes else 0
    print(f"{len(writes)} writes over {last:,} CPU cycles to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
