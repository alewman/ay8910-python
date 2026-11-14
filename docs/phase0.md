# Phase 0: what this core is, what judges it, and how it was built

Written 2026-11-11, with the build, while Aubrey was away. The decisions marked
**(decided)** were made here so the work could proceed; each says why and can be
reversed before anything leaves this repository. Nothing has been pushed or
published.

## Why a core

General Instrument's AY-3-8910 and Yamaha's YM2149 are one programmer's model in
many machines: the MSX, the ZX Spectrum 128, the Amstrad CPC, the Atari ST, a
long list of arcade boards, and, inside a Sunsoft mapper, the Famicom's
*Gimmick!*. By the family's extraction rule a chip more than one machine needs is
its own core. Its first user is famicom-python (mapper 69's 5B sound, which that
board does not have yet), so this is a new core, not an extraction.

## Scope

| Part | What differs | In scope |
| --- | --- | --- |
| **AY-3-8910** | the reference: 16-step envelope, two I/O ports, 16 DAC levels | yes |
| AY-3-8912, AY-3-8913 | the same die in 28 and 24 pins: port A only, no ports | yes, as data |
| **YM2149** | 32-step envelope at twice the rate, 32 DAC levels, the /SEL pin halving the clock, every register bit read back | yes, as data |
| **Sunsoft 5B** | a YM2149 with /SEL low for good, no ports, no read path | yes, as data |
| AY-3-8914, 8916, 8917 | registers in another order, other read-back | later, as data |
| AY8930, YM2203/2608/2610's SSG | an expanded mode; the SSG inside an FM chip | no: other chips |

What differs between parts is data on a `PSGVariant`, as sn76489-python's
`PSGVariant` and ym2413-python's `OPLLVariant`, not subclasses.

## Sources gathered

All fetched into `reference/` (ignored) by `scripts/fetch_references.py`, pinned by
commit or SHA-256.

| Source | Licence | What it is here |
| --- | --- | --- |
| lvd2/ay-3-8910_reverse_engineered @ cf8d14d: deathsoft's transistor-level schematic of the AY-3-8910 from die photographs, and lvd's Verilog model of it (`rtl/ay_model.v`) | GPL-3.0 | **the judge** of the AY parts, at every input clock |
| nukeykt/YM2203-LLE @ 817387f: the YM2203C from its die; its SSG block is Yamaha's PSG | GPL-2.0 | the judge of what the Yamaha parts' registers sound like, step by step |
| MAME `src/devices/sound/ay8910.cpp`, `.h` @ 518bb5e | BSD-3-Clause | read and cited: hardware-tested read-back, DAC measurements, its own model's rules |
| dnotq/ym2149_audio @ ce6654e: a YM2149 in VHDL, written from deathsoft's schematic and a real chip | BSD-3-Clause | read; not run (below) |
| true-grue/ayumi @ 07c08b4 | MIT | its measured YM2149 DAC table |
| General Instrument, *AY-3-8910/8912/8913 Programmable Sound Generator* data sheet (8 pages) | manufacturer | the programmer's model, pins, pull-ups |
| Yamaha, *YM2149 SSG* catalog LSI-2121492 (1992-09) | manufacturer | /SEL, the 32-step envelope, the DAC's levels (Fig. 1) |
| NESdev wiki, *Sunsoft 5B audio*, *Sunsoft FME-7*, *NSFe*; forum thread 17741 | community, hardware-tested | the 5B: rainwarrior's hardware verifications and level survey |
| bbbradsmith/nes-audio-tests @ 99ef107 | (test ROMs) | rainwarrior's 5B test programs: the 5B streams |

## Licence (decided; the account corrected 2026-11-14)

The core is MIT, like the family. Both judges are GPL: they are fetched, built
locally (`validation/build_referees.sh`) and run as closed boxes by
`validation/ay_tb.v` and `validation/ssg_ref.c`, which only drive their pins. No
code of theirs is here.

**What happened, for the record.** When this core was built (2026-11-11) the
judges' sources were also *read* for the chip's behaviour, under the family's
working rule of the time ("read, cite by file and line, never copy"): chip.py
cited `ay_model.v` by line nine times, variants.py once more, and variants.py and
claims.md cited YM2203-LLE's `fmopn.c`. This paragraph used to say so as a decision. The family charter of
2026-11-14 forbids it: a GPL program's source is not opened while writing the code
it informs. The provenance audit ([provenance.md](provenance.md)) found no
transcription, only facts learned by reading, and flagged four behaviours. On
2026-11-14 a session that saw neither the GPL sources nor the flagged code
re-established those four from the documents and from the die model's pins, run
as a closed box ([rederived.md](rederived.md)), rewrote the code that holds them,
and replaced every citation of the two sources with what was measured or read
elsewhere. From then on both judges are **closed box only**.

Icarus Verilog has no `trireg` nets, which the die model uses for stored charge.
`validation/icarus_port.py` makes a build-time copy of the model, in the ignored
build folder, with each `trireg` turned into a wire and a weak keeper; the regular
expression that does it contains none of the model's text.

## The judges, and why these

**The AY's die (the judge).** deathsoft redrew the AY-3-8910 from its die at
transistor level and lvd wrote the Verilog to match the schematic, gate for gate
and latch for latch, with unit delays only where order matters. It is not an
emulator's idea of the chip. (What this paragraph said of its insides, ripple
counters, transparent latches, a bus that keeps charge, was learned by reading its
source in 2026-11; see "Licence". Its pins show the last of them: rederived.md,
item 3.) Run under Icarus it manages
about 10,000 clocks a second, so a hundred million clocks is three hours of
processor time.

**Yamaha's die, one chip removed.** No die-derived model of the YM2149 is
published that a search on 2026-11-11 turned up (lvd2's is the AY; dnotq's is
written from the AY's schematic). The nearest silicon is the SSG
inside the YM2203, which nukeykt transcribed. It is the same programmer's model
with the 32-step envelope, but a different machine: one counter serves the three
tones and the envelope in turn. So it cannot be compared clock for clock with a
core built on the AY's machine, and it is not known which of the two machines the
YM2149 itself is. It judges what each register setting *sounds like*
(`scripts/ssg_referee.py`), and where the two dies part is recorded
(claims.md, "Where the judges disagree").

**MAME** is an emulator: evidence, never a judge. It was read, not run: building
its device outside MAME needs a stand-in for most of `emu.h`, and with a
die-derived judge at every clock an emulator's vote would decide nothing. Its
rules that differ from the die's are listed in claims.md.

**dnotq's VHDL** was read, not run. It flattens every tone period below 6 and
noise period below 5 to a constant on purpose (`ym2149_audio.vhd` lines 731-762,
832: ultrasonic periods are useless in an all-digital system), so as a detector
it would report the short periods the die settles.

## Decisions made here, for review

1. **One engine, the AY's (decided).** The Yamaha parts run the AY die's machine
   with their own data. Everything the YM2203's die can be asked agrees (levels,
   rates, shapes, the noise, period 0 as 1); what it cannot be asked, timing
   inside a step, is the AY's, on trust. The alternative, a second engine after
   the YM2203's SSG, would claim the YM2149 is that machine, which nothing in
   hand shows.
2. **A write is an instant (decided).** The AY's registers are latches open for
   as long as the bus strobe lasts, and a shape write holds the envelope in reset
   for that long. The core takes a write as an instant between two input clocks,
   which is what a board with CPU-cycle timing can say. A strobe's width is not
   modelled, and the die model was only ever written to in the clock's low half
   (claims.md, "Open").
3. **The time unit is the input clock** (decided, as the siblings), so the host
   never knows the divider: one `tick()` per CPU cycle on the Famicom. `tick()`
   exists beside `run(clocks)` because PyPy runs a loop of one inside a hot loop
   badly: `run(1)` measured 335 ns a call, `tick()` 41 ns.
4. **The output is DAC codes per input clock** (decided): 0-15 on an AY, 0-31 on
   a Yamaha part, plus `mix()` through the part's DAC table. Loads, filters and
   amplifiers are the board's.
5. **`record=False`** (decided) for a board that polls `levels()` after each
   `tick`: the per-clock queue the referee and the kit use would otherwise grow
   without bound.
6. **Default DAC tables (decided)**: measured ones for the AY (Westcott's
   voltages) and the YM2149 (ayumi's); the catalog's ladder for the 5B, whose
   only measurement is that it is 1.5 dB a step with 0 and 1 silent.
7. **An AY's unused register bits read back the internal bus (decided)**: 0 after
   an address byte, the byte just written otherwise. That is what the die
   model's pins show, measured closed box (rederived.md, item 3): charge on a
   floating bus, which on a real chip leaks away in some time the model does not
   have. The usual sequence, address then read, gives the 0 that MAME records as
   hardware-tested. Re-derived 2026-11-14 and kept over MAME's "always 0",
   which covers only that sequence.
8. **An output port reads its pins, the latch ANDed with the outside (decided).**
   At the die model's pins a port's read is its pins in both directions, the
   latch when nothing fights an output, and X when the outside does
   (rederived.md, item 4). Both data sheets give the pins pull-ups and GI's
   recommends grounding a pin to signal on it, so the outside is taken to win
   low. No judge decides this.
9. **The power-on state is /RESET's** (decided, as sn76489-python): a real part
   powers on at random.

## Open questions

- Which machine is the YM2149's: the AY's divider and five counters, or the
  YM2203's shared counter? A transcription of a YM2149's die, or of the 5B's,
  would settle it. Until then the Yamaha parts' timing inside a step is
  unverified.
- The phase of the /SEL divider's flip-flop: which of the two input clocks the
  halved clock ticks on is not known. The core ticks on the second after /RESET.
- The 5B's amplifier (it compresses above volume 14) and its level against the
  2A03 are the board's, with rainwarrior's measurements (README, "For a board").
- A real YM2149's envelope restart, measured at the pin, would say which die's
  first step it has (claims.md).

## The ladder

0. This document.
1. The core, every input clock equal to the AY's die model on synthetic streams.
2. The Yamaha parts against Yamaha's silicon, as far as it goes.
3. Music: the 5B's writes from famicom-python running *Gimmick!* and
   rainwarrior's tests, against the die model.
4. Seeded faults, and a conformance kit for ports.
5. Adoption by famicom-python (its session's), then the other boards.

Results are in [validation.md](validation.md).
