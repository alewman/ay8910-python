#!/usr/bin/env python
# SPDX-License-Identifier: MIT
"""Seed faults into the chip, one at a time, and check the tests catch each.

    python scripts/mutation.py [--jobs N] [--examples-only]

A gate that cannot fail proves nothing. Each mutant changes one place in
``src/ay8910_python/chip.py`` or ``variants.py`` -- a rule the chip is known to
have, broken the way a port might break it -- and the gate is the fast tests
(``pytest -m "not referee"``: the rules of tests/test_chip.py and the conformance
examples, whose traces were put to the die model when they were made), stopping at
the first failure. With ``--examples-only`` the gate is the conformance examples
alone, which is what a port in another language has. A mutant the gate misses is
listed, and needs a test.
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "ay8910_python"

#: (what is broken, the file, the exact text, its replacement)
MUTANTS = [
    (
        "strobe a clock early",
        "chip.py",
        "STROBE_PHASE = 2\nCOUNT_PHASE = 3",
        "STROBE_PHASE = 1\nCOUNT_PHASE = 3",
    ),
    (
        "count four clocks after the strobe",
        "chip.py",
        "STROBE_PHASE = 2\nCOUNT_PHASE = 3",
        "STROBE_PHASE = 2\nCOUNT_PHASE = 6",
    ),
    (
        "tones low out of reset",
        "chip.py",
        "self.tone_output = [1, 1, 1]",
        "self.tone_output = [0, 0, 0]",
    ),
    (
        "counters free out of reset",
        "chip.py",
        "self.tone_held = [True, True, True]",
        "self.tone_held = [False, False, False]",
    ),
    (
        "tone expires above its period",
        "chip.py",
        "counts[channel] >= periods[channel]",
        "counts[channel] > periods[channel]",
    ),
    (
        "tone period 0 is 4096",
        "chip.py",
        "self.tone_period[channel] = (coarse & 0x0F) << 8 | fine",
        "self.tone_period[channel] = ((coarse & 0x0F) << 8 | fine) or 4096",
    ),
    (
        "coarse tone period eight bits wide",
        "chip.py",
        "self.tone_period[channel] = (coarse & 0x0F) << 8 | fine",
        "self.tone_period[channel] = coarse << 8 | fine",
    ),
    (
        "a held tone counter is compared",
        "chip.py",
        "if not held[channel] and counts[channel] >= periods[channel]:",
        "if counts[channel] >= periods[channel]:",
    ),
    (
        "a period write restarts its tone",
        "chip.py",
        "            self.tone_period[channel] = (coarse & 0x0F) << 8 | fine\n",
        "            self.tone_period[channel] = (coarse & 0x0F) << 8 | fine\n            self.tone_count[channel] = 0\n",
    ),
    (
        "the strobe shuts with its clock",
        "chip.py",
        "return self.phase == (STROBE_PHASE + 1) & 7",
        "return False",
    ),
    (
        "noise steps on every expiry",
        "chip.py",
        "            self.noise_half ^= 1\n            if not self.noise_half:\n                self._shift_noise()",
        "            self._shift_noise()",
    ),
    (
        "noise steps on the other expiry",
        "chip.py",
        "if not self.noise_half:",
        "if self.noise_half:",
    ),
    (
        "noise taps 16 and 14",
        "chip.py",
        "feedback = ((noise >> 16) ^ (noise >> 13)) & 1",
        "feedback = ((noise >> 16) ^ (noise >> 14)) & 1",
    ),
    (
        "noise taps 16 and 2 (the 15-bit pair moved up)",
        "chip.py",
        "feedback = ((noise >> 16) ^ (noise >> 13)) & 1",
        "feedback = ((noise >> 16) ^ (noise >> 2)) & 1",
    ),
    (
        "noise register sixteen bits",
        "chip.py",
        "| feedback | (noise == 0)) & 0x1FFFF",
        "| feedback | (noise == 0)) & 0xFFFF",
    ),
    (
        "an empty noise register stays empty",
        "chip.py",
        "| feedback | (noise == 0)) & 0x1FFFF",
        "| feedback) & 0x1FFFF",
    ),
    (
        "noise heard uninverted",
        "chip.py",
        "noise = (~self.noise_register >> 16) & 1",
        "noise = (self.noise_register >> 16) & 1",
    ),
    (
        "noise heard at bit 0",
        "chip.py",
        "noise = (~self.noise_register >> 16) & 1",
        "noise = ~self.noise_register & 1",
    ),
    (
        "noise period six bits wide",
        "chip.py",
        "self.noise_period = registers[NOISE_PERIOD] & 0x1F",
        "self.noise_period = registers[NOISE_PERIOD] & 0x3F",
    ),
    (
        "an AY envelope steps on every expiry",
        "chip.py",
        "if self._envelope_top == 15:",
        "if False:",
    ),
    (
        "a Yamaha envelope steps on every second expiry",
        "chip.py",
        "if self._envelope_top == 15:",
        "if True:",
    ),
    (
        "envelope period 0 is twice as fast (MAME's AY)",
        "chip.py",
        "if not self.envelope_held and self.envelope_count >= self.envelope_period:",
        "if (not self.envelope_held or not self.envelope_period) and self.envelope_count >= self.envelope_period:",
    ),
    (
        "a late restart clears the whole counter",
        "chip.py",
        "self.envelope_count &= 1",
        "self.envelope_count = 0",
    ),
    (
        "a late restart holds the counter",
        "chip.py",
        "            self.envelope_count &= 1\n            self.envelope_held = False",
        "            self.envelope_count &= 1\n            self.envelope_held = True",
    ),
    (
        "an early restart does not hold the counter",
        "chip.py",
        "        else:\n            self.envelope_count = 0\n            self.envelope_held = True",
        "        else:\n            self.envelope_count = 0\n            self.envelope_held = False",
    ),
    (
        "the second half starts a clock late",
        "chip.py",
        "        return self.phase > COUNT_PHASE",
        "        return self.phase > COUNT_PHASE + 1",
    ),
    (
        "a restart keeps the halving flip-flop",
        "chip.py",
        "        self.envelope_half = 0\n        self.envelope_step = 0\n        self.envelope_holding",
        "        self.envelope_step = 0\n        self.envelope_holding",
    ),
    (
        "a restart keeps the step",
        "chip.py",
        "        self.envelope_step = 0\n        self.envelope_holding = False\n",
        "        self.envelope_holding = False\n",
    ),
    (
        "a restart leaves the period counter running",
        "chip.py",
        "        if self._counters_counted():\n            self.envelope_count &= 1\n            self.envelope_held = False\n        else:\n            self.envelope_count = 0\n            self.envelope_held = True\n",
        "",
    ),
    (
        "a restart does not release a held level",
        "chip.py",
        "        self.envelope_holding = False\n        self.envelope_rising",
        "        self.envelope_rising",
    ),
    (
        "attack read from the alternate bit",
        "chip.py",
        "self.registers[ENVELOPE_SHAPE] & ATTACK)",
        "self.registers[ENVELOPE_SHAPE] & ALTERNATE)",
    ),
    (
        "a ramp one step short",
        "chip.py",
        "        if self.envelope_step <= self._envelope_top:",
        "        if self.envelope_step < self._envelope_top:",
    ),
    (
        "without CONTINUE the level holds where it ended",
        "chip.py",
        "            self.envelope_holding = True\n            self.envelope_level = 0\n",
        "            self.envelope_holding = True\n",
    ),
    (
        "HOLD ignores ALTERNATE",
        "chip.py",
        "ends_high = self.envelope_rising ^ bool(shape & ALTERNATE)",
        "ends_high = self.envelope_rising",
    ),
    (
        "ALTERNATE does not turn the ramp",
        "chip.py",
        "                self.envelope_rising = not self.envelope_rising\n",
        "                pass\n",
    ),
    (
        "HOLD does not hold",
        "chip.py",
        "        elif shape & HOLD:\n            self.envelope_holding = True",
        "        elif shape & HOLD:\n            self.envelope_holding = False",
    ),
    (
        "mixer bits enable instead of disable",
        "chip.py",
        "tone_gate = self.tone_output[channel] | (mixer >> channel)",
        "tone_gate = self.tone_output[channel] | ~(mixer >> channel)",
    ),
    (
        "tone and noise are ORed",
        "chip.py",
        "            if not tone_gate & noise_gate & 1:",
        "            if not (tone_gate | noise_gate) & 1:",
    ),
    (
        "noise gates from the tone bits",
        "chip.py",
        "noise_gate = noise | (mixer >> (channel + 3))",
        "noise_gate = noise | (mixer >> channel)",
    ),
    (
        "a Yamaha volume drives 2v",
        "chip.py",
        "codes.append((volume & 0x0F) * 2 + 1 if wide else volume & 0x0F)",
        "codes.append((volume & 0x0F) * 2 if wide else volume & 0x0F)",
    ),
    (
        "the envelope bit is bit 5",
        "chip.py",
        "            if volume & 0x10:",
        "            if volume & 0x20:",
    ),
    (
        "the volume acts at the next strobe",
        "chip.py",
        "            self._compare()\n        self._levels = self._mix_levels()",
        "            self._compare()\n",
    ),
    (
        "any address byte selects",
        "chip.py",
        "self.selected = (value & 0xF0) == 0",
        "self.selected = True",
    ),
    (
        "a deselecting byte moves the latch",
        "chip.py",
        "        if self.selected:\n            self.address = value & 0x0F",
        "        self.address = value & 0x0F",
    ),
    (
        "an address byte leaves the bus charged",
        "chip.py",
        "            self.address = value & 0x0F\n        self.bus = 0",
        "            self.address = value & 0x0F",
    ),
    (
        "a data write leaves the bus as it was",
        "chip.py",
        "            self.bus = value & 0xFF\n            self._write_register(self.address, self.bus)",
        "            self._write_register(self.address, value & 0xFF)",
    ),
    (
        "an output port reads its latch alone",
        "chip.py",
        "            levels &= self.registers[register]",
        "            levels = self.registers[register]",
    ),
    (
        "an input port reads its latch",
        "chip.py",
        "        if self._port_is_output(register):\n            levels &= self.registers[register]",
        "        levels &= self.registers[register]",
    ),
    (
        "port directions swapped",
        "chip.py",
        "(0x40 if register == PORT_A else 0x80)",
        "(0x80 if register == PORT_A else 0x40)",
    ),
    (
        "an unbonded port reads the outside",
        "chip.py",
        "if outside is not None and self._port_bonded(register):",
        "if outside is not None:",
    ),
    (
        "the divider ignores the halving",
        "chip.py",
        "if self._divider_count >= self.clock_divider:",
        "if self._divider_count >= 1:",
    ),
    (
        "reset keeps the registers",
        "chip.py",
        "        self.registers = [0] * 16\n",
        "        self.registers = getattr(self, 'registers', [0] * 16)\n",
    ),
    (
        "reset keeps the divider's phase",
        "chip.py",
        "        self._divider_count = 0\n        self.phase = 0\n",
        "        self._divider_count = 0\n        self.phase = getattr(self, 'phase', 0)\n",
    ),
    (
        "the AY keeps eight bits of every register",
        "variants.py",
        "    register_masks: tuple[int, ...] = REGISTER_WIDTH_MASKS",
        "    register_masks: tuple[int, ...] = ALL_BITS",
    ),
    (
        "the YM2149 has a 16-step envelope",
        "variants.py",
        '    "YM2149", envelope_steps=32,',
        '    "YM2149", envelope_steps=16,',
    ),
    (
        "the 5B runs at the full clock",
        "variants.py",
        "clock_divider=2, dac=DAC_5B",
        "clock_divider=1, dac=DAC_5B",
    ),
    (
        "the AY-3-8912 has port B",
        "variants.py",
        'AY8912 = PSGVariant("AY-3-8912", ports="A")',
        'AY8912 = PSGVariant("AY-3-8912", ports="AB")',
    ),
    (
        "the 5B's code 1 sounds",
        "variants.py",
        "DAC_YM_DATASHEET = (0.0, 0.0, *(2.0 ** ((code - 31) / 4) for code in range(2, 32)))",
        "DAC_YM_DATASHEET = (0.0, *(2.0 ** ((code - 31) / 4) for code in range(1, 32)))",
    ),
    (
        "the Yamaha ladder at 3 dB a step",
        "variants.py",
        "DAC_YM_DATASHEET = (0.0, 0.0, *(2.0 ** ((code - 31) / 4) for code in range(2, 32)))",
        "DAC_YM_DATASHEET = (0.0, 0.0, *(2.0 ** ((code - 31) / 2) for code in range(2, 32)))",
    ),
    (
        "the strobe stays open all the turn",
        "chip.py",
        "return self.phase == (STROBE_PHASE + 1) & 7",
        "return True",
    ),
    (
        "the count that lets a counter go does not count it",
        "chip.py",
        "            counts[channel] += 1\n",
        "            counts[channel] += not held[channel]\n",
    ),
]

EXAMPLES_ONLY = "--examples-only" in sys.argv[1:]


def gate(tree: Path) -> bool:
    """True when the gate passes (the mutant survives)."""
    env = dict(os.environ, PYTHONPATH=f"{tree / 'src'}{os.pathsep}{tree / 'scripts'}")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if EXAMPLES_ONLY:
        examples = str(tree / "examples" / "conformance")
        command = [sys.executable, "-m", "ay8910_python.conformance", "check", examples]
    else:
        marker = "not referee"
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-x",
            "-m",
            marker,
            "-p",
            "no:cacheprovider",
        ]
    result = subprocess.run(command, cwd=tree, env=env, capture_output=True, text=True)
    return result.returncode == 0


def run_mutant(mutant: tuple[str, str, str, str]) -> tuple[str, bool]:
    name, file, old, new = mutant
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp)
        for part in ("src", "tests", "scripts", "examples"):
            shutil.copytree(ROOT / part, tree / part, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(ROOT / "pyproject.toml", tree / "pyproject.toml")
        shutil.copy(ROOT / "README.md", tree / "README.md")
        target = tree / "src" / "ay8910_python" / file
        text = target.read_text()
        target.write_text(text.replace(old, new))
        return name, gate(tree)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--examples-only", action="store_true", help="gate on the examples alone")
    args = parser.parse_args()
    for name, file, old, _ in MUTANTS:
        if (PACKAGE / file).read_text().count(old) != 1:
            print(f"mutant {name!r}: its text is not in {file} exactly once")
            return 2
    with multiprocessing.Pool(args.jobs) as pool:
        results = pool.map(run_mutant, MUTANTS)
    survivors = [name for name, survived in results if survived]
    for name, survived in results:
        print(f"{'SURVIVED' if survived else 'caught  '}  {name}")
    print(f"{len(results) - len(survivors)} of {len(results)} caught")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
