# SPDX-License-Identifier: MIT
"""The conformance kit: the examples still trace the same, and the formats hold."""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest

from ay8910_python import PSG, VARIANTS
from ay8910_python.conformance import (
    TRACE_HEADER,
    Event,
    Manifest,
    check,
    diff_traces,
    load_manifest,
    main,
    manifest_from_dict,
    trace_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "conformance"
MANIFESTS = sorted(EXAMPLES.glob("*.json"))


def test_there_are_examples() -> None:
    assert len(MANIFESTS) == 19
    assert {load_manifest(path).variant for path in MANIFESTS} == set(VARIANTS)


@pytest.mark.parametrize("path", MANIFESTS, ids=lambda path: path.stem)
def test_this_chip_still_writes_every_reference_trace(path: Path) -> None:
    reference = path.with_suffix(".trace").read_text(encoding="utf-8").splitlines()
    assert diff_traces(reference, trace_manifest(load_manifest(path))) is None


def test_check_passes_on_the_examples() -> None:
    assert check(EXAMPLES) == []


def test_make_examples_is_reproducible() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "make_examples.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def small() -> Manifest:
    events = (
        Event(0, "write", 7, 0x3E),
        Event(0, "write", 8, 15),
        Event(4, "write", 0, 2),
        Event(40, "read", 0),
        Event(41, "write", 7, 0x7E),
        Event(41, "write", 14, 0x21),
    )
    return Manifest("small", "AY-3-8910", events, 60)


def test_a_trace_is_the_output_at_every_clock() -> None:
    lines = list(trace_manifest(small()))
    assert lines[:4] == [TRACE_HEADER, "# small AY-3-8910", "L 0 0 0 0", "P 0 255 255"]
    assert "R 40 2" in lines and "P 41 33 255" in lines
    assert lines[-1] == "# end 60 clocks 6 events"
    chip = PSG()
    chip.write_register(7, 0x3E)
    chip.write_register(8, 15)
    chip.run(4)
    chip.write_register(0, 2)
    chip.run(56)
    outputs = [(0, 0, 0), *chip.take_outputs()]
    changes = {
        int(clock): (int(a), int(b), int(c))
        for kind, clock, a, b, c in (line.split() for line in lines if line.startswith("L "))
    }
    current = None
    for clock, expected in enumerate(outputs):
        current = changes.get(clock, current)
        assert current == expected


def test_diff_names_the_first_line_that_differs() -> None:
    reference = list(trace_manifest(small()))
    assert diff_traces(reference, reference) is None
    changed = [*reference[:5], "L 9 9 9 9", *reference[6:]]
    difference = diff_traces(reference, changed)
    assert difference is not None and difference.line == 6
    assert diff_traces(reference, reference[:-1]).external == "(end of trace)"


def test_a_manifest_round_trips_through_json() -> None:
    import json

    manifest = small()
    assert manifest_from_dict(json.loads(manifest.to_json())) == manifest


def manifest_dict(**changes: object) -> dict:
    base = {"version": 1, "name": "x", "variant": "AY-3-8910", "clocks": 9, "events": []}
    return {**base, **changes}


@pytest.mark.parametrize(
    "bad",
    [
        manifest_dict(version=2),
        manifest_dict(variant="AY-3-8911"),
        manifest_dict(extra=0),
        manifest_dict(events=[[5, "poke", 0, 0]]),
        manifest_dict(events=[[5, "write", 0]]),
        manifest_dict(events=[[5, "write", 0, 256]]),
        manifest_dict(events=[[5, "write", 0, 0]], clocks=3),
        manifest_dict(events=[[5, "write", 0, 0], [4, "write", 0, 0]]),
        manifest_dict(events=[[5, "divider", 2, 0]]),
        manifest_dict(events=[[5, "divider", 3, 0]], variant="YM2149"),
    ],
)
def test_a_bad_manifest_is_refused(bad: dict) -> None:
    with pytest.raises(ValueError):
        manifest_from_dict(bad)


def test_the_command_line(tmp_path: Path) -> None:
    path = MANIFESTS[0]
    out = io.StringIO()
    assert main(["trace", str(path)], stdout=out) == 0
    assert out.getvalue() == path.with_suffix(".trace").read_text(encoding="utf-8")
    port = tmp_path / "port.trace"
    assert main(["trace", str(path), "--out", str(port)], stdout=io.StringIO()) == 0
    assert main(["diff", str(path), str(port)], stdout=io.StringIO()) == 0
    port.write_text(port.read_text().replace("L 0 0 0 0", "L 0 1 0 0"))
    out = io.StringIO()
    assert main(["diff", str(path), str(port)], stdout=out) == 1
    assert "line 3" in out.getvalue()
    assert main(["trace", str(tmp_path / "missing.json")], stdout=io.StringIO()) == 2
    assert main(["check", str(EXAMPLES)], stdout=io.StringIO()) == 0
