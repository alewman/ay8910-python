# Validation: the oracles, the ladder, and every run

All runs are of 2026-11-11, on PyPy 7.3.23 (Python 3.11.15) unless a line says
otherwise; the fast tests also on CPython 3.14.4. The core's commit for each run
is given with it.

## Tiers

1. **hardware**: a measurement of a real chip (rainwarrior's tests on a *Gimmick!*
   cartridge; Westcott's and ayumi's DAC levels).
2. **manufacturer**: GI's AY-3-8910/8912/8913 data sheet; Yamaha's YM2149 catalog.
3. **die-derived**: a transcription of the chip's silicon from die photographs.
4. **emulator**: another program; evidence, never a judge.

## The oracles

| Oracle | Tier | Role | Pin |
| --- | --- | --- | --- |
| deathsoft's schematic of the AY-3-8910 and lvd's Verilog model of it | die-derived | **the judge**: three codes, sixteen port pins and every read, at every input clock | `reference/src/ay-3-8910_reverse_engineered` @ cf8d14d, GPL-3.0, run under Icarus Verilog 14.0 (devel, oss-cad-suite 2026-10-05) as `ay_ref` |
| The SSG of nukeykt's YM2203-LLE | die-derived, one chip removed | Yamaha's silicon: what each register setting sounds like | `reference/src/YM2203-LLE` @ 817387f, GPL-2.0, built as `ssg_ref` |
| rainwarrior's hardware tests of the 5B (NESdev wiki, with forum posts) | hardware | the 5B's rules, as far as a recording shows them | `reference/docs/Sunsoft_5B_audio.wiki` (SHA-256 in `scripts/fetch_references.py`) |
| GI's data sheet, Yamaha's catalog | manufacturer | the programmer's model; Yamaha's DAC ladder | `reference/docs/*.pdf` |
| MAME's ay8910 | emulator | read and cited, not run | `reference/src/mame` @ 518bb5e, BSD-3 |
| dnotq's ym2149_audio | hand-written HDL | read, not run | @ ce6654e, BSD-3 |

`validation/ay_tb.v` and `validation/ssg_ref.c` drive the judges and copy nothing
(phase0.md, "Licence").

### How the die model is driven

`validation/ay_tb.v` holds /RESET over 32 clocks, then for each clock applies
that clock's events with the clock low, raises and lowers the clock, and samples
the pins after the falling edge. A write is an address strobe and a data strobe,
each a fraction of a clock; nothing is held across a clock (phase0.md, decision
2). Three things about the model shaped the bench:

- /RESET is released with the clock **high**. Released with it low, the model's
  divider flip-flops come out of reset with both halves equal and oscillate
  forever (two cross-coupled gates of equal delay); a real chip would fall one
  way.
- The data bus is pulled low at rest, or the model's chip-select decoder sees
  floating address bits. A read of a deselected chip therefore gives 0; the core
  says $FF, and `scripts/referee.py` allows for it.
- The outside drives a port's pins only while the port is an input. Fought over,
  the model's pin is X.

The model takes about 0.1 ms a clock under Icarus: some 10,000 clocks a second
on one core of this machine.

## Rung 1: every input clock, synthetic streams

`scripts/referee.py` runs `scripts/streams.py`'s 24 streams through the core and
the die model from /RESET: silence; every tone period from 0 up, on every phase
of the divider; periods changed under running counters; every noise period; the
noise register's whole 131,071-step sequence; all sixteen envelope shapes at
three periods; envelope periods 0 to 20 and up to $FFFF with the shape rewritten
on every phase; seeded restarts; every mixer and volume value; every register
read back; deselecting address bytes with reads and writes after them; both
ports both ways; /RESET on every phase; the longest periods left to run; five
streams of 6,000 seeded writes and reads each; four of 8,000 seeded events of
every kind (writes, bare address and data bytes, reads, the ports' pins, /RESET).

| Part | Compared | Streams | Die clocks | Different |
| --- | --- | ---: | ---: | ---: |
| AY-3-8910 | codes, port pins, reads | 24 | 25,725,326 | **0** |
| AY-3-8912, AY-3-8913 | codes | 24 each | 25,725,326 each | **0** |
| YM2149, Sunsoft 5B | codes, halved | 24 each | 25,725,326 each | **0** |

Run at commit 667d769 (`python scripts/referee.py --variant ...`, one stream to
a process, the die model run once per stream and each part compared with it). An
earlier run of the first 20 streams on the AY-3-8910 at 55cf7b2 was equal too;
between the two the engine changed only in `run()` becoming `tick()` in a loop,
a port callback firing only on a change, and an unobservable bus update being
dropped.

The other parts are the same engine with other data, so their rows show that
the data is wired in right, not five independent results. A Yamaha part's
thirty-two codes are halved before comparing: its volume `2v + 1` and its
envelope (twice the steps, twice as often) both come down to the AY's value, so
the AY's die judges everything about them but the envelope's lowest bit. The 5B
is run two input clocks to the die's one.

Getting there took four corrections to a programmer's-model engine, each a
disagreement with the die: the tones are high out of /RESET and a cleared counter
is held until it counts; the noise steps on the second expiry, not the first; a
period written in the clock after the strobe is compared at once; and an
envelope restarted in the second half of the divider's eight keeps its
counter's lowest bit (chip.py's docstrings; claims.md).

## Rung 2: the Yamaha parts against Yamaha's silicon

`scripts/ssg_referee.py` (core at 667d769). The YM2203's SSG serves its tones and envelope in turn from one counter,
so it is compared on waveforms, not clocks: per case the registers are written,
both sides run, and each channel's output is reduced to runs of (level, steps),
which must be equal run for run (the first and last of a window dropped; either
side allowed up to three runs' head start).

| Cases | What | Steps watched, each part | Different |
| --- | --- | ---: | ---: |
| 15 | tone periods 0-12, 100, $FFF on three channels | 59,962 | 0 |
| 32 | every noise period, 700 steps of the register each | 695,800 | 0 |
| 65 | sixteen shapes at envelope periods 0, 1, 2, 5; period 300 | 44,040 | 0 |
| 32 | every volume value, fixed and envelope | 9,216 | 0 |
| 64 | every mixer value (a channel given tone and noise together is left out) | 57,600 | 0 |
| **208** | YM2149 and Sunsoft 5B | **866,618** | **0** |

Where it differs is the step a register is written in. Measured for the
envelope (`--restarts`): from a shape write to the first change of level,

| Envelope period | Core (the AY's die), counts | The YM2203's die, counts |
| ---: | --- | --- |
| 1 | 1 | 3 |
| 2 | 3 or 4 | 5 |
| 3 | 5 or 6 | 7 |
| 5 | 9 or 10 | 11 |
| 8 | 15 or 16 | 17 |

(the core's two values are the lowest-bit rule, by where in the divider's eight
the write lands). Tone and noise period writes differ likewise by which of the
shared counter's turns they catch. This is claims.md's disagreement 2, and why
the Yamaha parts' timing inside a step is listed there as unverified.

The harness selects the YM2203's prescaler $2F before anything else: the model
skips its logic on calls where its FM clocks have not moved, and with the
power-on prescaler that leaves the SSG's own divider unclocked.

## Rung 3: programs

`scripts/export_board_streams.py` records every CPU write to $C000-$FFFF from
famicom-python (@ c497645, read only: it has no 5B of its own yet and is only
watched through its bus observers), with the CPU cycle each lands on:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=../famicom-python/src python scripts/export_board_streams.py \
    ROM --frames N [--press 300:8,480:8,700:8,900:8] --out validation/streams/NAME.stream
```

*Gimmick! (Japan) (En)* (SHA-1 of the `.nes` file
bb19be49dad26236b03c91d086e90abdbc94da1d; 2,400 frames from power-on, Start
pressed at frames 300, 480, 700 and 900; what was on screen was not looked at)
and six of rainwarrior's 5B hardware test programs (nes-audio-tests @ 99ef107,
the `_nrom` builds, from power-on). `scripts/referee.py --stream FILE
--half-clock` then puts each to the die model at every clock, twice: as an
AY-3-8910 given half as many clocks (CPU cycle `n` is die clock `n // 2`), whole;
and as the 5B itself, in the CPU's own clocks, its codes halved.

| Program | Bus writes (address and data bytes) | CPU cycles | Die clocks | AY-3-8910 | Sunsoft 5B |
| --- | ---: | ---: | ---: | --- | --- |
| *Gimmick!*, 2,400 frames | 18,418 | 71,472,866 | 35,756,433 | **0 different** | **0 different** |
| `envelope_5b`, 1,800 frames | 74 | 48,209,143 | 24,124,571 | **0 different** | **0 different** |
| `phase_5b`, 1,500 frames | 376 | 43,780,558 | 21,910,279 | **0 different** | **0 different** |
| `clip_5b`, 1,500 frames | 98,788 | 44,577,601 | 22,308,800 | **0 different** | **0 different** |
| `noise_5b`, 1,200 frames | 40 | 26,781,999 | 13,410,999 | **0 different** | **0 different** |
| `db_5b`, 900 frames | 78 | 21,793,553 | 10,916,776 | **0 different** | **0 different** |
| `sweep_5b`, 1,200 frames | 34 | 8,926,565 | 4,483,282 | **0 different** | **0 different** |
| **7 programs** | 117,808 | | **132,911,140** | **0** | **0** |

Run with the engine as of 55cf7b2 (each run takes up to an hour of the die
model); `sweep_5b`, `db_5b` and `noise_5b` were run again at 667d769: equal on
both parts (28,811,057 die clocks).

What the programs hold the core to, read from the streams themselves:

- *Gimmick!* writes three tones at fixed volumes 0-10 and never opens the noise
  or gives a channel to the envelope (as the wiki says of it): 18,418 writes
  whose data bytes land on every one of the sixteen CPU cycles of the chip's
  count, 457 to 689 times each.
- `clip_5b` is 98,788 writes, almost all to the three volumes: cycle-counted
  square waves made by rewriting the volume. `phase_5b` rewrites a tone period
  between $FFF and 0 fifty times. `noise_5b` opens the noise at period 0;
  `envelope_5b` reaches its first three shape writes; `db_5b` is one tone at
  volume 12.
- Each test is cut off at its frame count, and `sweep_5b`'s 5B half begins after
  it: that stream is the test's initialisation writes and silence, and counts
  for little.

These are the die model's verdicts on the *writes* real programs make. They are
not comparisons with recordings: famicom-python has no recording of a 5B, and
the hardware facts used here are the wiki's reports of rainwarrior's results.

## Rung 4: seeded faults

`scripts/mutation.py` breaks one rule of `chip.py` or `variants.py` at a time
and runs the fast tests (`pytest -m "not referee"`) to the first failure. At
667d769: 59 faults, **59 of 59 caught**; with `--examples-only` (the gate is the
19 conformance examples, what a port in another language has) **56 of 59**. After
the re-derivation of 2026-11-14 the 21 faults that touched rewritten code were
re-pointed at it, under the same names, and two were added for the new code ("the
strobe stays open all the turn", "the count that lets a counter go does not count
it"): **61 of 61 caught**, and **58 of 61** by the examples alone. The three they
miss, then and now:

- two errors in the DAC tables (the examples carry codes, not levels: the tables
  are data a port copies, checked by `tests/test_variants.py`);
- "a deselecting byte moves the latch": an **equivalent mutant at the pins**. A
  deselected chip ignores reads and writes, and the next good address byte sets
  the latch anyway. The die does keep the latch (its load is gated by the chip
  select), the core does too, and only a test that looks at `chip.address` can
  tell.

One more was found equivalent while building the list and was pruned from the
core instead of kept as dead state: updating the internal bus on a read (the bus
keeps only what the read found there).

The tests' own gate was checked the other way: `tests/test_referee.py` moves the
strobe one clock and requires the die comparison to fail.

## The fast tests

`python -m pytest -q -m "not referee"`: 207 tests (the rules of
`tests/test_chip.py`, the parts and DAC tables, the kit and its 19 examples), a
few seconds on CPython 3.14 and on PyPy. `python -m pytest -q -m referee`: 11 more
against the two built judges, about a minute. CI (`.github/workflows/ci.yml`) runs the
first set and ruff on PyPy 3.11.

## Re-derivation of 2026-11-14

The four behaviours the provenance audit flagged were re-established from the
die model's pins and the documents ([rederived.md](rederived.md)) and their code
rewritten (commit fb4279d), by a session that saw neither the GPL sources nor the
flagged code. Then everything above was run again on the rewritten engine:

| Run | Result |
| --- | --- |
| `scripts/probe_die.py --compare`: the ten probes of rederived.md, core against die | **0 different** |
| Rung 1: the 24 synthetic streams, five parts | **25,725,326 clocks each, 0 different** |
| Rung 2: `scripts/ssg_referee.py`, YM2149 and 5B | **208 cases, 866,618 steps each, 0 different**; the `--restarts` table unchanged |
| Rung 3: the seven board streams, as the AY-3-8910 and as the 5B | **132,911,140 die clocks, 0 different** |
| Rung 4: seeded faults | **61 of 61** caught; 58 of 61 by the examples alone |
| Tests | 218 pass (207 fast on PyPy and CPython, 11 against the built judges); ruff clean |

The engine's behaviour did not change.

## Not verified

Said plainly, so that nothing above reads as wider than it is:

- **The Yamaha parts are not clock-exact against Yamaha silicon.** No YM2149 die
  model exists to compare with; the YM2203's SSG agrees on waveforms and differs
  on write timing. Their timing inside a step, their restart, and the /SEL
  divider's phase are the AY's machine and a guess respectively.
- **The envelope's lowest code bit on a Yamaha part** is judged only by the
  YM2203 waveform cases, not at every clock.
- **MAME and dnotq's VHDL were read, not run.**
- **No recording of a real chip was compared.** famicom-python has rainwarrior's
  5B test ROMs and the NewRisingSun recordings for other mappers, but no 5B
  recording; the 5B's hardware facts here are the wiki's reports of rainwarrior's
  results, not measurements redone.
- **A write strobe's width**, and with it the envelope held in reset for as long
  as the strobe lasts.
- **An output port fought by the outside**; **the YM2149's read-back of unused
  bits** (MAME's report); **the DAC tables** (others' measurements, not
  re-measured); the 8912 and 8913 as separate dies.
- The core has not been run inside a board.
