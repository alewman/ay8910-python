#!/usr/bin/env python
# SPDX-License-Identifier: MIT
"""Ask the AY-3-8910's die model short questions at its pins, and print the answers.

    python scripts/probe_die.py [--only NAME] [--json FILE]

The die model (``ay_ref``, built by validation/build_referees.sh) is run as a
closed box: each probe is a stream of bus events (validation/ay_tb.v's kinds) and
the answer is what the pins show, the three channel codes, the port pins and the
bytes read. Nothing here knows how the model is built. The answers are the
evidence of docs/rederived.md, and this script is how they are remade.

Every probe starts from /RESET (the power-on one, or a pulse between probes), so
its times are input clocks after /RESET is released: an event at ``t`` lands
before the rising edge of clock ``t``, and sample ``t`` is the pins after it.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from referee import READ, READ_DATA, RESET, SELECT, WRITE, WRITE_DATA, core, die, die_samples

from ay8910_python import AY8910

PINS_A = 2

Event = tuple[int, int, int, int]

#: With ``--compare``, every probe's stream is also run through the core, and any
#: clock or read where the two differ is listed here.
COMPARE = False
DIFFERENCES: list[str] = []


class Probe:
    """One question: its events, relative to /RESET, and how long to watch."""

    def __init__(self, key: object, length: int) -> None:
        self.key = key
        self.length = length
        self.events: list[Event] = []

    def write(self, at: int, register: int, value: int) -> Probe:
        self.events.append((at, WRITE, register, value))
        return self

    def event(self, at: int, kind: int, a: int = 0, b: int = 0) -> Probe:
        self.events.append((at, kind, a, b))
        return self


def run(probes: list[Probe]) -> list[tuple[list[tuple[int, ...]], list[int]]]:
    """Run probes back to back, a /RESET pulse before each but the first, in one
    die run; return each one's samples and reads."""
    stream: list[Event] = []
    starts = []
    base = 0
    for index, probe in enumerate(probes):
        if index:
            stream.append((base, RESET, 0, 0))
        starts.append(base)
        stream.extend(
            (base + at, kind, a, b) for at, kind, a, b in sorted(probe.events, key=lambda e: e[0])
        )
        base += probe.length
    reads_per_probe: list[list[int]] = [[] for _ in probes]
    owner = []
    for index, probe in enumerate(probes):
        owner += [index] * sum(1 for e in probe.events if e[1] in (READ, READ_DATA))
    with tempfile.TemporaryDirectory() as tmp:
        out, reads = die(stream, base, Path(tmp))
        samples = list(die_samples(out))
    if COMPARE:
        ours_reads: list[int] = []
        ours = list(core(AY8910, stream, base, ours_reads))
        first = next(
            (t for t, (a, b) in enumerate(zip(ours, samples, strict=True)) if a != b), None
        )
        if first is not None:
            DIFFERENCES.append(f"clock {first}: core {ours[first]}, die {samples[first]}")
        if ours_reads != reads:
            DIFFERENCES.append(f"reads: core {ours_reads}, die {reads}")
    for index, value in zip(owner, reads, strict=True):
        reads_per_probe[index].append(value)
    return [
        (samples[start : start + probe.length], reads_per_probe[index])
        for index, (start, probe) in enumerate(zip(starts, probes, strict=True))
    ]


def changes(samples: list[tuple[int, ...]], channel: int = 0, after: int = 0) -> list[int]:
    """The sample indices at which a channel's code differs from the one before."""
    return [
        t
        for t in range(max(after, 1), len(samples))
        if samples[t][channel] != samples[t - 1][channel]
    ]


# -- the probes ---------------------------------------------------------------------------


def tone_after_reset() -> dict:
    """A tone of period P written at clock 0: where its first edges fall. And period 1
    written at clock w, for w over three eights: where its first edge falls."""
    probes = [
        Probe(("P", period), 120).write(0, 7, 0x3E).write(0, 8, 15).write(0, 0, period)
        for period in range(5)
    ]
    probes += [
        Probe(("w", w), 80).write(0, 7, 0x3E).write(0, 8, 15).write(w, 0, 1) for w in range(24)
    ]
    result: dict = {"edges_by_period": {}, "first_edge_by_write_clock": {}}
    for probe, (samples, _) in zip(probes, run(probes), strict=True):
        kind, value = probe.key
        if kind == "P":
            result["edges_by_period"][value] = changes(samples)[:6]
        else:
            result["first_edge_by_write_clock"][value] = changes(samples, after=value)[0]
    return result


def tone_period_writes() -> dict:
    """A tone of period 40 running; after its first edge E, period p is written at
    clock E + d. Answer: the clock of the next edge, as an offset from E."""
    first = run([Probe("e", 400).write(0, 7, 0x3E).write(0, 8, 15).write(0, 0, 40)])[0][0]
    edge = changes(first)[0]
    probes = []
    for d in range(1, 8 * 12 + 1):
        for p in range(1, 14):
            probe = Probe((d, p), edge + d + 8 * 16)
            probe.write(0, 7, 0x3E).write(0, 8, 15).write(0, 0, 40).write(edge + d, 0, p)
            probes.append(probe)
    table: dict = {}
    for probe, (samples, _) in zip(probes, run(probes), strict=True):
        d, p = probe.key
        later = changes(samples, after=edge + 1)
        table.setdefault(d, {})[p] = later[0] - edge if later else None
    return {"first_edge": edge, "next_edge_offset[d][p]": table}


def tone_open_strobe() -> dict:
    """After the edge E of a period-40 tone, period 0, 1 or 2 written at E + d (d =
    1-17: the clock after the expiring strobe, and the clocks after the next two
    strobes among them). Answer: the next two edges, as offsets from E."""
    first = run([Probe("e", 400).write(0, 7, 0x3E).write(0, 8, 15).write(0, 0, 40)])[0][0]
    edge = changes(first)[0]
    probes = []
    for d in range(1, 18):
        for p in (0, 1, 2):
            probe = Probe((d, p), edge + d + 8 * 8)
            probe.write(0, 7, 0x3E).write(0, 8, 15).write(0, 0, 40).write(edge + d, 0, p)
            probes.append(probe)
    table: dict = {}
    for probe, (samples, _) in zip(probes, run(probes), strict=True):
        d, p = probe.key
        later = changes(samples, after=edge + 1)[:2]
        table.setdefault(d, {})[p] = [t - edge for t in later]
    return {"first_edge": edge, "next_two_edges[d][p]": table}


def envelope_period_writes() -> dict:
    """Envelope period 20 restarted (shape $08) at clock 0; its first expiry falls
    near 8 * 20. Period p is written at clock 8 * 10 + d. Answer: the clock of the
    first step (15 to 14)."""
    probes = []
    for d in range(0, 8 * 12):
        for p in (1, 2, 5, 9, 10, 11, 12):
            probe = Probe((d, p), 8 * 10 + d + 8 * 30)
            probe.write(0, 7, 0x3F).write(0, 8, 0x10).write(0, 11, 20).write(0, 13, 0x08)
            probe.write(8 * 10 + d, 11, p)
            probes.append(probe)
    table: dict = {}
    for probe, (samples, _) in zip(probes, run(probes), strict=True):
        d, p = probe.key
        found = changes(samples)
        table.setdefault(8 * 10 + d, {})[p] = found[0] if found else None
    return {"first_step[write_clock][p]": table}


def held_after_reset() -> dict:
    """Noise and envelope at period 0 and 1 from clock 0: their first changes."""
    probes = []
    for period in (0, 1, 2):
        noise = Probe(("noise", period), 400).write(0, 7, 0x37).write(0, 8, 15).write(0, 6, period)
        envelope = Probe(("envelope", period), 400).write(0, 7, 0x3F).write(0, 8, 0x10)
        envelope.write(0, 11, period).write(0, 13, 0x08)
        probes += [noise, envelope]
    result: dict = {}
    for probe, (samples, _) in zip(probes, run(probes), strict=True):
        name, period = probe.key
        found = changes(samples)[:8]
        result.setdefault(name, {})[period] = [(t, samples[t][0]) for t in found]
    return result


def envelope_restarts(periods=(0, 1, 2, 3, 4, 5)) -> dict:
    """Shape $08 written at clock 0 (the first restart), then again at clock 16 + j.
    Answer: clocks from the second write to the first change of level (15 to 14),
    and the level the write leaves."""
    probes = []
    for period in periods:
        span = 8 * 2 * max(period, 1) * 2 + 8
        for j in range(span):
            at = 16 + j
            probe = Probe((period, j), at + 8 * 2 * max(period, 1) * 3 + 16)
            probe.write(0, 7, 0x3F).write(0, 8, 0x10).write(0, 11, period).write(0, 13, 0x08)
            probe.write(at, 13, 0x08)
            probes.append(probe)
    table: dict = {}
    for probe, (samples, _) in zip(probes, run(probes), strict=True):
        period, j = probe.key
        at = 16 + j
        after = changes(samples, after=at + 1)
        table.setdefault(period, {})[j] = {
            "level_after_write": samples[at][0],
            "first_change": (after[0] - at) if after else None,
        }
    return table


def envelope_restart_period_0() -> dict:
    """Envelope period 4 restarted at clock 0, so its counter is even (4) after the
    count of clock 27 and odd (3) after that of clock 19. At clock ``at`` period 0
    is written and the shape rewritten at once. Answer: clocks to the first step.
    Period 0 expires at any strobe that compares the counter, so this shows whether
    a restart leaves the counter compared or held."""
    probes = []
    for at in range(16, 40):
        probe = Probe(at, at + 80).write(0, 7, 0x3F).write(0, 8, 0x10).write(0, 11, 4)
        probe.write(0, 13, 0x08).write(at, 11, 0).write(at, 13, 0x08)
        probes.append(probe)
    table = {}
    for probe, (samples, _) in zip(probes, run(probes), strict=True):
        found = changes(samples, after=probe.key + 1)
        table[probe.key] = found[0] - probe.key if found else None
    return {"first_step_after[at]": table}


def envelope_restart_releases_hold() -> dict:
    """Shape $09 (down, then held at 0) left to finish, then rewritten."""
    probe = Probe("hold", 2000).write(0, 7, 0x3F).write(0, 8, 0x10).write(0, 11, 1)
    probe.write(0, 13, 0x09).write(1000, 13, 0x09)
    samples, _ = run([probe])[0]
    return {
        "level_before": samples[999][0],
        "level_after": [samples[t][0] for t in range(1000, 1040, 4)],
    }


def read_back() -> dict:
    """Unused register bits: reads after a data write with no address byte between,
    after an address byte, after a long wait, after a deselected stretch."""
    widths = {}
    cases: dict = {}
    p = Probe("each", 2000)
    t = 4
    order = []
    for register in range(14):
        for value in (0xFF, 0x00, 0xA5, 0x5A):
            p.event(t, SELECT, register).event(t, WRITE_DATA, 0, value).event(t, READ_DATA)
            p.event(t + 1, READ, register)
            order.append((register, value))
            t += 2
    q = Probe("sequences", 30000)
    seq = [
        (
            "write $B7 to R1, bare read",
            [(4, SELECT, 1, 0), (4, WRITE_DATA, 0, 0xB7), (4, READ_DATA, 0, 0)],
        ),
        ("then a second bare read", [(5, READ_DATA, 0, 0)]),
        ("then address byte 1, read", [(6, READ, 1, 0)]),
        ("then a bare read", [(7, READ_DATA, 0, 0)]),
        (
            "R1 <- $B7, 20000 clocks, bare read",
            [(8, SELECT, 1, 0), (8, WRITE_DATA, 0, 0xB7), (20008, READ_DATA, 0, 0)],
        ),
        (
            "R6 <- $FF, deselect ($16), bare read (deselected)",
            [
                (20010, SELECT, 6, 0),
                (20010, WRITE_DATA, 0, 0xFF),
                (20010, SELECT, 0x16, 0),
                (20010, READ_DATA, 0, 0),
            ],
        ),
        ("then address byte 6, read", [(20011, READ, 6, 0)]),
        (
            "R1 <- $B7, deselect ($11), bare write $55, address 1, read",
            [
                (20012, SELECT, 1, 0),
                (20012, WRITE_DATA, 0, 0xB7),
                (20012, SELECT, 0x11, 0),
                (20012, WRITE_DATA, 0, 0x55),
                (20012, READ, 1, 0),
            ],
        ),
        (
            "R13 <- $B7, bare read",
            [(20014, SELECT, 13, 0), (20014, WRITE_DATA, 0, 0xB7), (20014, READ_DATA, 0, 0)],
        ),
        (
            "R8 <- $E3, bare read",
            [(20016, SELECT, 8, 0), (20016, WRITE_DATA, 0, 0xE3), (20016, READ_DATA, 0, 0)],
        ),
        (
            "R0 <- $C3, then address 1, read R1 (holds $07)",
            [(20018, SELECT, 0, 0), (20018, WRITE_DATA, 0, 0xC3), (20018, READ, 1, 0)],
        ),
        (
            "R1 <- $B7, read port A (input, pins $FF), address 1, read",
            [
                (20020, SELECT, 1, 0),
                (20020, WRITE_DATA, 0, 0xB7),
                (20020, READ, 14, 0),
                (20021, READ, 1, 0),
            ],
        ),
    ]
    labels = []
    for label, events in seq:
        for at, kind, a, b in events:
            q.event(at, kind, a, b)
        labels += [label] * sum(1 for e in events if e[1] in (READ, READ_DATA))
    (_, each_reads), (_, seq_reads) = run([p, q])
    for index, (register, value) in enumerate(order):
        bare, addressed = each_reads[2 * index], each_reads[2 * index + 1]
        widths.setdefault(register, []).append(
            {
                "written": f"{value:02X}",
                "bare_read": f"{bare:02X}",
                "after_address": f"{addressed:02X}",
            }
        )
    for label, value in zip(labels, seq_reads, strict=True):
        cases.setdefault(label, []).append(f"{value:02X}")
    return {"per_register": widths, "sequences": cases}


def port_reads() -> dict:
    """Port A and B as inputs with the outside driving, then as outputs with
    another value in the latch: what a read returns and what the pins show."""
    p = Probe("ports", 200)
    p.write(4, 14, 0x12).write(4, 15, 0x34)
    p.event(5, PINS_A, 0x5A).event(5, PINS_A + 1, 0xC3)
    p.event(6, READ, 14).event(6, READ, 15)
    p.write(8, 7, 0xC0)
    p.event(9, READ, 14).event(9, READ, 15)
    p.write(10, 14, 0x9E)
    p.event(11, READ, 14)
    p.write(12, 7, 0x00)
    p.event(13, READ, 14).event(13, READ, 15)
    samples, reads = run([p])[0]
    pins = {t: (f"{samples[t][3]:02X}", f"{samples[t][4]:02X}") for t in (6, 9, 11, 13)}
    names = [
        "input, latch $12/$34, outside $5A/$C3: read A",
        "input: read B",
        "outputs: read A",
        "outputs: read B",
        "output A, latch rewritten $9E: read A",
        "inputs again: read A",
        "inputs again: read B",
    ]
    return {
        "reads": dict(zip(names, [f"{v:02X}" for v in reads], strict=True)),
        "pins_A_B_at": pins,
    }


PROBES: dict[str, Callable[[], dict]] = {
    "tone_after_reset": tone_after_reset,
    "tone_period_writes": tone_period_writes,
    "tone_open_strobe": tone_open_strobe,
    "envelope_period_writes": envelope_period_writes,
    "held_after_reset": held_after_reset,
    "envelope_restarts": envelope_restarts,
    "envelope_restart_period_0": envelope_restart_period_0,
    "envelope_restart_releases_hold": envelope_restart_releases_hold,
    "read_back": read_back,
    "port_reads": port_reads,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only", action="append", help="a probe to run (repeatable)")
    parser.add_argument("--json", type=Path, help="write every answer here")
    parser.add_argument("--compare", action="store_true", help="also run the core on every probe")
    args = parser.parse_args(argv)
    global COMPARE
    COMPARE = args.compare
    answers = {}
    for name, probe in PROBES.items():
        if args.only and name not in args.only:
            continue
        answers[name] = probe()
        print(name, json.dumps(answers[name])[:2000], flush=True)
    if args.json:
        args.json.write_text(json.dumps(answers, indent=1, default=str))
    if COMPARE:
        print(f"core against die on every probe: {len(DIFFERENCES)} differences")
        for line in DIFFERENCES:
            print("  ", line)
    return 1 if DIFFERENCES else 0


if __name__ == "__main__":
    sys.exit(main())
