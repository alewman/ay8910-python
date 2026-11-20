# SPDX-License-Identifier: MIT
"""The conformance kit: manifests of bus events, and traces of what the chip drives.

A port of this core proves itself by running each manifest in
``examples/conformance`` and writing the trace below, then comparing it with the
one committed beside the manifest (docs/conformance.md). The committed traces were
made by this core; the AY-3-8910 ones were checked against the die model when they
were made (scripts/make_examples.py).

    ay8910-conformance trace MANIFEST.json            # the trace, to stdout
    ay8910-conformance diff MANIFEST.json PORT.trace  # the first line that differs
    ay8910-conformance check examples/conformance     # every example, against its trace

Trace format, version 1:

    # ay8910-trace 1
    # NAME VARIANT
    L <clock> <a> <b> <c>     the three channels' DAC codes after input clock <clock>
    R <clock> <value>         a byte read, <clock> input clocks into the run
    P <clock> <a> <b>         the levels the chip drives on ports A and B
    # end <clocks> clocks <events> events

An ``L`` line is written before the first clock (``clock`` 0) and then after every
input clock that leaves the codes different from the last line's; a ``P`` line
likewise at 0 and whenever an event changes what the chip drives ($FF for a port
that is an input). The codes hold between lines, so two equal traces are the same
output at every input clock.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import TextIO

from .chip import PSG
from .variants import VARIANTS

TRACE_HEADER = "# ay8910-trace 1"
MANIFEST_SCHEMA_VERSION = 1

#: Event kinds: which of ``a`` and ``b`` each uses (docs/conformance.md).
KINDS = {
    "write": "register, value: an address byte and a data byte",
    "read": "register: an address byte and a read",
    "select": "the address byte alone",
    "data": "a data byte alone (in b)",
    "read_data": "a read alone",
    "reset": "/RESET",
    "pins_a": "the levels the outside drives onto port A",
    "pins_b": "the same for port B",
    "divider": "the /SEL pin's effect: 1 or 2 input clocks per internal clock",
}


@dataclass(frozen=True)
class Event:
    """One event, applied when ``t`` input clocks have run."""

    t: int
    kind: str
    a: int = 0
    b: int = 0

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown event kind {self.kind!r} ({', '.join(KINDS)})")
        if self.t < 0 or not 0 <= self.a <= 0xFF or not 0 <= self.b <= 0xFF:
            raise ValueError(f"event out of range: {self}")


@dataclass(frozen=True)
class Manifest:
    """A run: the variant, the events in clock order, and how many clocks to run."""

    name: str
    variant: str
    events: tuple[Event, ...]
    clocks: int

    def __post_init__(self) -> None:
        if self.variant not in VARIANTS:
            raise ValueError(f"unknown variant {self.variant!r} ({', '.join(VARIANTS)})")
        if any(b.t < a.t for a, b in pairwise(self.events)):
            raise ValueError("events must be in clock order")
        if self.events and self.events[-1].t > self.clocks:
            raise ValueError("an event falls after the end of the run")
        if not VARIANTS[self.variant].has_sel_pin and any(e.kind == "divider" for e in self.events):
            raise ValueError(f"{self.variant} has no /SEL pin to change the divider with")
        if any(e.kind == "divider" and e.a not in (1, 2) for e in self.events):
            raise ValueError("the divider is 1 or 2")

    def to_json(self) -> str:
        """The manifest's JSON form, one event to a line."""
        events = ",\n".join(
            f"  {json.dumps([event.t, event.kind, event.a, event.b])}" for event in self.events
        )
        head = {
            "version": MANIFEST_SCHEMA_VERSION,
            "name": self.name,
            "variant": self.variant,
            "clocks": self.clocks,
        }
        fields = "".join(
            f" {json.dumps(key)}: {json.dumps(value)},\n" for key, value in head.items()
        )
        return f'{{\n{fields} "events": [\n{events}\n ]\n}}\n'


@dataclass(frozen=True)
class TraceDifference:
    """The first line where two traces differ (1-based), and both lines."""

    line: int
    reference: str
    external: str

    def __str__(self) -> str:
        return (
            f"traces differ at line {self.line}\n"
            f"  reference: {self.reference}\n  external:  {self.external}"
        )


def trace_manifest(manifest: Manifest) -> Iterator[str]:
    """Run ``manifest`` on this chip, yielding the trace's lines (without newlines)."""
    chip = PSG(VARIANTS[manifest.variant], record=False)
    outside = [0xFF, 0xFF]
    driven = [0xFF, 0xFF]
    chip.port_a_in = lambda: outside[0]
    chip.port_b_in = lambda: outside[1]

    def drive(port: int, value: int) -> None:
        driven[port] = value

    chip.port_a_out = lambda value: drive(0, value)
    chip.port_b_out = lambda value: drive(1, value)

    yield TRACE_HEADER
    yield f"# {manifest.name} {manifest.variant}"
    last = chip.levels()
    last_driven = (driven[0], driven[1])
    yield "L 0 {} {} {}".format(*last)
    yield "P 0 {} {}".format(*last_driven)

    def advance(t: int) -> Iterator[str]:
        nonlocal last
        while chip.clock < t:
            chip.tick()
            now = chip.levels()
            if now != last:
                last = now
                yield "L {} {} {} {}".format(chip.clock, *now)

    for event in manifest.events:
        yield from advance(event.t)
        kind = event.kind
        if kind == "write":
            chip.write_register(event.a, event.b)
        elif kind == "read":
            chip.select(event.a)
            yield f"R {chip.clock} {chip.read()}"
        elif kind == "select":
            chip.select(event.a)
        elif kind == "data":
            chip.write(event.b)
        elif kind == "read_data":
            yield f"R {chip.clock} {chip.read()}"
        elif kind == "reset":
            clock = chip.clock
            chip.reset()
            chip.clock = clock
        elif kind == "pins_a":
            outside[0] = event.a
        elif kind == "pins_b":
            outside[1] = event.a
        else:
            chip.clock_divider = event.a
        if (driven[0], driven[1]) != last_driven:
            last_driven = (driven[0], driven[1])
            yield "P {} {} {}".format(chip.clock, *last_driven)
    yield from advance(manifest.clocks)
    yield f"# end {chip.clock} clocks {len(manifest.events)} events"


def diff_traces(reference: Iterable[str], external: Iterable[str]) -> TraceDifference | None:
    """The first line where ``external`` differs from ``reference``, or ``None``."""
    line = 0
    ref_iter, ext_iter = iter(reference), iter(external)
    while True:
        line += 1
        ref = next(ref_iter, None)
        ext = next(ext_iter, None)
        if ref is None and ext is None:
            return None
        ref = None if ref is None else ref.rstrip("\n")
        ext = None if ext is None else ext.rstrip("\n")
        if ref != ext:
            return TraceDifference(line, ref or "(end of trace)", ext or "(end of trace)")


def manifest_from_dict(value: object) -> Manifest:
    """A manifest from its JSON form (docs/conformance.md), strictly checked."""
    if not isinstance(value, dict):
        raise ValueError("a manifest is a JSON object")
    unknown = set(value) - {"version", "name", "variant", "events", "clocks"}
    if unknown:
        raise ValueError(f"unknown manifest keys: {sorted(unknown)}")
    if value.get("version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"unsupported manifest version {value.get('version')!r}")
    events = []
    for index, item in enumerate(value.get("events", [])):
        if not isinstance(item, list) or len(item) != 4:
            raise ValueError(f"event {index} is not [t, kind, a, b]")
        events.append(Event(*item))
    return Manifest(
        name=str(value["name"]),
        variant=str(value["variant"]),
        events=tuple(events),
        clocks=int(value["clocks"]),
    )


def load_manifest(path: str | Path) -> Manifest:
    return manifest_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def check(directory: Path) -> list[str]:
    """Every manifest in ``directory`` whose trace differs from the one beside it."""
    failures = []
    for path in sorted(directory.glob("*.json")):
        reference = path.with_suffix(".trace").read_text(encoding="utf-8").splitlines()
        if diff_traces(reference, trace_manifest(load_manifest(path))) is not None:
            failures.append(path.stem)
    return failures


def main(argv: list[str] | None = None, *, stdout: TextIO | None = None) -> int:
    """``trace`` writes the reference trace; ``diff`` reports the first difference;
    ``check`` runs every example in a directory.

    Exit status: 0 on success or equal traces, 1 on a difference, 2 on bad input.
    """
    out = stdout or sys.stdout
    parser = argparse.ArgumentParser(prog="ay8910-conformance", description=main.__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    trace_cmd = commands.add_parser("trace", help="write the reference trace of a manifest")
    trace_cmd.add_argument("manifest")
    trace_cmd.add_argument("--out", help="file to write (default: stdout)")
    diff_cmd = commands.add_parser("diff", help="compare an external trace with the reference")
    diff_cmd.add_argument("manifest")
    diff_cmd.add_argument("trace", help="trace path, or '-' for stdin")
    check_cmd = commands.add_parser("check", help="check every example in a directory")
    check_cmd.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    if args.command == "check":
        failures = check(args.directory)
        for name in failures:
            print(f"differs: {name}", file=out)
        print(f"{len(failures)} differ", file=out)
        return 1 if failures else 0
    try:
        manifest = load_manifest(args.manifest)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=out)
        return 2
    if args.command == "trace":
        text = "".join(line + "\n" for line in trace_manifest(manifest))
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
        else:
            out.write(text)
        return 0
    try:
        handle = sys.stdin if args.trace == "-" else open(args.trace, encoding="utf-8")  # noqa: SIM115
    except OSError as exc:
        print(f"error: {exc}", file=out)
        return 2
    with handle:
        difference = diff_traces(trace_manifest(manifest), handle)
    if difference is None:
        print(f"{manifest.name}: traces are identical", file=out)
        return 0
    print(f"{manifest.name}: {difference}", file=out)
    return 1


if __name__ == "__main__":
    sys.exit(main())
