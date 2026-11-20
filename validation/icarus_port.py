#!/usr/bin/env python
# SPDX-License-Identifier: MIT
"""Make a copy of a Verilog file that Icarus Verilog can run: ``trireg`` to a keeper.

    python validation/icarus_port.py IN.v OUT.v

Icarus has no ``trireg`` (a net that keeps its last driven value while nothing
drives it). Each ``trireg [H:L] name;`` becomes a plain ``wire`` with a weak keeper
on it (``ay_tb_keeper``, in validation/ay_tb.v), which holds the same charge: a
strong driver wins and the keeper follows; with every driver released the keeper's
value is the net's. Nothing else is touched. The copy lands in
``reference/build-referees/`` (ignored) and is never committed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TRIREG = re.compile(r"^(\s*)trireg\s*(\[([^:\]]+):([^\]]+)\])?\s*(\w+)\s*;", re.MULTILINE)


def keeper(match: re.Match[str]) -> str:
    indent, span, high, low, name = match.groups()
    width = f"({high}) - ({low}) + 1" if span else "1"
    return f"{indent}wire {span or ''} {name}; ay_tb_keeper #(.W({width})) keep_{name} ({name});"


def main() -> int:
    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    text, count = TRIREG.subn(keeper, source.read_text())
    target.write_text(text)
    print(f"{target.name}: {count} trireg nets given keepers")
    return 0 if count else 1


if __name__ == "__main__":
    sys.exit(main())
