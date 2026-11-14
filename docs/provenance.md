# Provenance of ay8910-python

Audit of 2026-11-13 (family provenance audit, wave 1). It judges the repository
against the family charter's "Licences and provenance" section and the rules of
the sound-core restart: nothing copied or transcribed from GPL, LGPL or
unlicensed code; facts about the hardware are not code, but a fact counts only
when it was established on real hardware and stated in prose, or measured on a
closed box whose source was never opened. Code fragments stay closed wherever
they appear.

## How this audit was done

- Read in full: `src/ay8910_python/*.py`, `validation/*`, `docs/*.md`, the
  README, the git history (7 commits, no deleted files), `scripts/fetch_references.py`.
- Not opened: `rtl/ay_model.v` (lvd2, GPL-3.0), `fmopn.c` (YM2203-LLE, GPL-2.0),
  or any other GPL source. Only the licence files and `sch/README.md` of the lvd2
  checkout were read, for the licence and the schematic's origin.
- `pcengine-python/scripts/provenance_check.py --repo ay8910-python --reference R`
  for each R under `reference/src/`:
  - `mame` (BSD-3-Clause): 1 hit, a URL in `scripts/fetch_references.py`. Nothing.
  - `ayumi` (MIT): 1 hit, `DAC_YM_MEASURED` in `variants.py` is ayumi's table
    (stated in the code). See "cite" below.
  - `ym2149_audio` (BSD-3-Clause): no hits.
  - `ay-3-8910_reverse_engineered` (GPL-3.0) and `YM2203-LLE` (GPL-2.0): no
    hits. These two were run because reading them was this repository's
    documented practice (phase0.md, "Licence"); with no hits, the checker showed
    none of their text.

## What "0 different" means here

The core's three DAC codes (on the AY-3-8910 also its sixteen port pins and
every register read) were compared at every input clock with lvd's Verilog model
of deathsoft's transistor-level schematic of the AY-3-8910 die. The model ran
under Icarus Verilog as a black box (`ay_ref`):

- `validation/build_referees.sh` builds it from the pinned checkout. On the way,
  `validation/icarus_port.py` turns each `trireg` net into a wire with a weak
  keeper, in a git-ignored copy. Icarus has no `trireg`.
- `validation/ay_tb.v` drives the model's pins from an event file and samples
  them after each falling edge.
- `scripts/referee.py` runs each stream through both sides and compares them.

The streams:

- 24 synthetic streams: 25,725,326 clocks, 0 different, on each of the five
  parts (the Yamaha parts' 5-bit codes halved).
- Seven programs (*Gimmick!* and six of rainwarrior's 5B tests), recorded as bus
  writes from famicom-python: 132,911,140 die clocks, 0 different.

The Yamaha parts were also compared on waveforms (runs of level and length, not
clocks) with the SSG block of nukeykt's YM2203-LLE (GPL-2.0), driven by
`validation/ssg_ref.c`: 208 cases, 0 different. They differ, as recorded, on
when inside a step a write takes hold.

So the judges are closed boxes in the comparison. **But the build also read the
AY model's source while writing the engine.** phase0.md says so: "They were
read for the chip's behaviour and are cited by file and line". chip.py cites
`ay_model.v` by line nine times. That breaks charter rule 3: the source of a
GPL program is not opened while writing the code it informs. It is also the
pattern the audit standard names, behaviour "rewritten in Python with line
citations".

## Was anything transcribed?

No evidence of transcription:

- The Verilog is a gate-level model: ripple counters, transparent latches,
  charge-keeping nets (phase0.md). chip.py is a behavioural engine: integer
  counters, one strobe phase and one count phase, an envelope step counter.
- No identifier in chip.py looks like a netlist name.
- The checker found no shared prose, code shape, tables or quoted lines.

What came across is **facts about the circuit, read in GPL code**: where the
strobe and the count fall in the divider's eight, a counter held clear between
its expiry and the count, a write in the clock after the strobe compared at
once, the lowest counter bit having no clear, and the bus keeping charge. Most
of these are also pin behaviour that the closed-box comparison pins down. Some
are also stated by hardware tests in prose (period 0 acts as 1; phase counting;
no halt; the LFSR; envelope reset). Under the middle rule, only those hardware
statements and closed-box measurements count as sources. The code reading does
not.

## Verdicts, piece by piece

| Piece | Where its behaviour came from | Licence of the source | Verdict |
| --- | --- | --- | --- |
| Register map, register numbers, shape bits, the address byte's chip-select (DA7-DA4 = 0), the bus functions, pull-ups (chip.py) | GI data sheet; Yamaha catalog; Sunsoft_5B_audio (NESdev wiki) | manufacturer documents; wiki public domain | **clean** (the `psg_cs` citation dropped 2026-11-14) |
| Register widths, `REGISTER_WIDTH_MASKS` (variants.py) | GI data sheet "Register array"; MAME ay8910.cpp comment "Tested and confirmed on hardware" | manufacturer; BSD-3-Clause (a hardware statement in prose) | **clean** (the `reg6` citation replaced 2026-11-14 by MAME's statement and rederived.md, item 3) |
| Divide by eight; tone, noise and envelope rates (fT = f/16TP, and so on); period 0 acts as 1; a period shortened under the count ends the half-cycle at the next strobe; nothing restarts a tone or the noise | GI data sheet formulas; the wiki's "Period 0", "Phase counting" and "No halt" verifications (rainwarrior, real cartridge) | manufacturer; wiki public domain | **clean** |
| **Strobe and count as two phases of the eight (`STROBE_PHASE` 2, `COUNT_PHASE` 3 after /RESET); the held flip-flop that keeps a counter clear until the count; a period written in the clock after the strobe compared at once** | first read in the GPL model's source (wave 1). **Re-derived 2026-11-14** from closed-box probes of `ay_ref` (rederived.md, item 1: edges on phase 2 of 8; period 0 = 1 and no expiry at the first strobe after /RESET or an expiry; a period written in the clock after a strobe compared at once with the count that strobe saw; the counter counted in that same clock), the data sheet's divide-by-16 and the wiki's period-0 and phase-counting verifications | closed-box measurement; manufacturer; wiki | **clean (re-derived)**: code rewritten (`tick`, `_compare`, `_count`, `_strobe_open`, the open-strobe check in `_write_register`) from rederived.md; every probe and every stream equal at every clock |
| Noise: 17-bit register, taps 16 and 13, a 1 fed while empty, heard inverted (chip.py docstring, `_shift_noise`, `_mix_levels`) | the wiki's "LFSR verification" (hardware); MAME's prose comment "verified on AY-3-8910 and YM2149 chips" (mirrored pair); the whole 131,071-step sequence checked closed-box | wiki public domain; BSD-3-Clause | **clean**: the line citations gave way to these sources 2026-11-14. The zero-fill and the inversion, as start-up behaviour, are seen on the pins closed-box (`noise_sequence`, `resets`; rederived.md, item 1 b) |
| **Envelope restart in the second half of the eight keeps the counter's lowest bit (`_restart_envelope`, `_counters_counted`)** | first read in the GPL model's source (wave 1). **Re-derived 2026-11-14** closed box (rederived.md, item 2): over EP 0-5 and every clock of two step periods, a restart before the count gives `2·EP` counts to the first step; after it `2·EP - 1` when the counter was odd and `2·EP` when even, 240 of 240; period 0 written with the restart expires at the next strobe after the count, so the counter is not held | closed-box measurement of the die model only; no hardware statement | **clean (re-derived), kept as the default** and tagged MEASURED (closed box) only in claims.md. A non-default variant row was not made: no source gives the alternative (rederived.md, "Default or variant"); Aubrey may decide otherwise |
| Envelope shapes, 16 steps on every second expiry, 32 on every expiry, any shape write restarts (chip.py:367-395) | GI Fig. 1 and envelope formula; Yamaha catalog (4)-(6); the wiki's "Envelope phase reset" and "Envelope-Volume equivalence" verifications | manufacturer; wiki | **clean** |
| **Unused register bits read back the internal bus: 0 after an address byte, else the last byte written (`read`, `read_register`; phase0.md decision 7)** | first read in the GPL model's source (wave 1). **Re-derived 2026-11-14** closed box (rederived.md, item 3): every register 0-13 written with four bytes reads them whole with no address byte between and masked to its width after one; the charge stays 20,000 clocks; a deselecting byte and a deselected write change nothing | closed-box measurement; MAME's hardware statement (BSD-3-Clause) for the address-then-read case | **clean (re-derived)**: the measured behaviour kept (it contains MAME's statement; "always 0" would contradict the model with no hardware measurement against it). Code rewritten |
| **A port's read returns its pins in either direction (`_port_pins`)** | first read in the GPL model's source (wave 1). **Re-derived 2026-11-14** (rederived.md, item 4): GI's data sheet, "when in the 'input' mode, all pins will read normally high"; closed-box reads (inputs read the outside, not the latch; outputs read the latch on the pins); MAME's prose that an output port's read must return the outside's data (*Kid Niki*) | manufacturer; closed-box measurement; BSD-3-Clause prose (game observation) | **clean (re-derived)**: code rewritten; the fought output stays phase0.md decision 8 |
| Mixer (chip.py:399-421) | GI data sheet; Yamaha's `2v + 1` from the catalog | manufacturer | **clean** |
| Parts as data: 8912/8913 pinouts, YM2149 /SEL and all-bits read-back, the 5B (variants.py) | GI data sheet; Yamaha catalog; MAME's prose "YM2149: no anomaly"; the wiki | manufacturer; BSD-3-Clause; wiki | **clean** |
| `DAC_AY_MEASURED` | Matthew Westcott's 2001 measurement, public domain by him, quoted in MAME ay8910.cpp | public domain (via BSD-3-Clause) | **clean** (cited) |
| `DAC_AY_LOGARITHMIC`, `DAC_YM_DATASHEET`, `DAC_5B` | GI's "logarithmic steps"; Yamaha Fig. 1; the wiki's 1.5 dB with codes 0 and 1 silent | manufacturer; wiki | **clean**. The `fmopn.c:1846` citation replaced 2026-11-14 by a closed-box run of `ssg_ref` (one 32-step ramp shows 31 levels, the lowest 0) |
| `DAC_YM_MEASURED` | ayumi's `YM_dac_table`, a measurement of a real chip | MIT (Peter Sovietov) | **cite**: the MIT notice now sits beside the table (fixed in this audit) |
| conformance.py, the conformance kit and its 19 examples | own; the traces are this core's output, put to the die model closed-box | own | **clean** |
| scripts/ (streams, make_examples, mutation, referee, ssg_referee, export_board_streams, fetch_references) | own tooling | own | **clean** |
| validation/ay_tb.v | own testbench; uses only the model's port names (its interface) | own; drives GPL-3.0 code | **clean**. The built `ay_ref` is a GPL-3.0 combined work, never distributed (charter rule 6) |
| validation/ssg_ref.c | own harness; uses YM2203-LLE's header, its `fmopn_t` input and output fields and `FMOPN_Clock` (the interface) | own; links GPL-2.0+ code | **clean**. `ssg_ref` is a GPL-2.0+ combined work, never distributed |
| validation/icarus_port.py | own regular expression; the model is copied only into ignored build output | own | **clean** |
| tests/ | own; no GPL citations | own | **clean** |
| docs/claims.md, docs/phase0.md, README | cited `ay_model.v:1190` and `fmopn.c:1627-1679, 1846`; phase0.md "Licence (decided)" described reading the GPL judges while writing | | **clean (fixed 2026-11-14)**: restated as closed-box measurements and hardware statements; the `fmopn.c:1627-1679` claim (the YM2203 keeps only the used bits) dropped as unmeasured; phase0.md's account corrected, the reading recorded there and here |

Counts at the wave-1 audit: **clean 15, cite 2, rewrite 4, unclear 0**. After
the re-derivation of 2026-11-14 (below): **clean 20** (four re-derived, the docs
row fixed), **cite 1** (`DAC_YM_MEASURED`, its MIT notice in place), **rewrite 0**.

## The rewrite, and the alternative

The four **rewrite** items are behaviour, not text. What is needed is to
re-derive each from allowed sources:

- the data sheets
- the hardware statements on the NESdev wiki
- facts read off deathsoft's schematic as a drawing of the die (a hardware
  record)
- closed-box runs of `ay_ref`, made by a session that has not read `ay_model.v`

Then replace every `ay_model.v` and `fmopn.c` citation with what was measured or
read in a document. The harness and the 24 streams already exist, so this is
short work, and the engine will most likely come out the same. The envelope
lowest-bit rule is the exception: it may leave the part's default row (a
model-only behaviour, like pokey-python's U19 and U20), or stay as a measured
property of the die model with its tier stated.

The alternative, Aubrey's decision under charter rule 4, is to relicense the
core GPL-3.0 and credit lvd and deathsoft.

## The re-derivation (wave 2, item 3, 2026-11-14)

Done by a session that did not open `ay_model.v`, `fmopn.c` or anything else of
the two GPL judges, nor the flagged ranges of chip.py at 20b0fe9 (lines 13-26,
166-176, 198, 218-221, 233-242, 256-324, 335-360): the file was copied unread to
the git-ignored `trash/`, then printed with those ranges blanked by a script, and
the session worked from that view. The mutants of scripts/mutation.py that quoted
the flagged code were rewritten without being displayed (selected by a script
that compared their text with the unflagged lines).

- **Evidence**: [rederived.md](rederived.md), from `scripts/probe_die.py` (short
  streams put to `ay_ref` at its pins), GI's data sheet, the wiki's hardware
  verifications and MAME's prose (BSD-3-Clause).
- **Code**: the module docstring and `read`, `read_register`'s last line, the
  open-strobe check in `_write_register`, `_port_pins`, `tick`, `run`,
  `_strobe_open`, `_compare`, `_count` and `_restart_envelope` written again
  from rederived.md; the rest of chip.py kept, its citations replaced.
- **Result**: the engine's behaviour did not change. Every probe, the 24
  synthetic streams on all five parts, the seven board streams and the 208 Yamaha
  waveform cases are equal ([validation.md](validation.md), "Re-derivation of
  2026-11-14").
- **What remains the model's alone**: the envelope's second-half restart and the
  charge on the internal bus (claims.md, "Open").

## History

Every commit from 55cf7b2 (the first) carries the engine with its `ay_model.v`
line citations. No code from elsewhere was added and later removed. The
d025c96 change to the DAC ladders re-sourced two formulas from the data sheets.
The remote (github.com/alewman/ay8910-python) is **private**, so the history has
not been distributed. If the repository goes public after the rewrite, the old
commits still show an engine written with the GPL model open. Decide with the
rewrite whether to publish that history (nothing in it is transcribed) or start
the public history at the rewritten commit.

## Missing headers (family-wide, owed)

No source file carries an SPDX header (charter rule 2). Not fixed here.

## Citation fix made in this audit

- `src/ay8910_python/variants.py`: ayumi's MIT copyright and permission notice
  added beside `DAC_YM_MEASURED`. Ruff clean; the 207 fast tests pass.

## Sources

| Source | Licence or terms | Family use |
| --- | --- | --- |
| lvd2/ay-3-8910_reverse_engineered `rtl/ay_model.v` (lvd's Verilog of the die) | GPL-3.0 | **closed box only**. Off limits as text, and the single most useful AY reference: gate for gate from the die |
| deathsoft's AY-3-8910 schematic (`sch/`, from drsvanhay.de die photographs), (c) 2019 deathsoft, inside the same GPL-3.0 repository | GPL-3.0 (as a drawing) | **facts only**: a record of the die; read facts off the drawing, copy nothing of it |
| nukeykt/YM2203-LLE (`fmopn.c`), the YM2203 from its die | GPL-2.0-or-later | **closed box only** |
| MAME `ay8910.cpp`/`.h` (Couriersud and others) | BSD-3-Clause | **code OK (with notice)**. Its hardware statements in prose are usable facts |
| dnotq/ym2149_audio (Matthew Hagerty, VHDL) | BSD-3-Clause | **code OK (with notice)**; read, not used |
| true-grue/ayumi (Peter Sovietov) | MIT | **code OK (with notice)**: the YM2149 DAC table, notice kept |
| Matthew Westcott's AY voltages (comp.sys.sinclair, 2001) | public domain | **code OK** (facts, cited) |
| General Instrument AY-3-8910/8912/8913 data sheet | manufacturer document | **facts only** |
| Yamaha YM2149 catalog LSI-2121492 | manufacturer document | **facts only** |
| NESdev wiki: Sunsoft 5B audio, Sunsoft FME-7, NSFe | public domain (wiki disclaimer) | **facts only** (rainwarrior's hardware results) |
| NESdev forum threads 17741 and 17745 (rainwarrior) | forum posts | **facts only**. The forum bans AI-written posts; reading is unaffected. Never post there as the model |
| bbbradsmith/nes-audio-tests (rainwarrior's 5B test ROMs) | test programs, licence not checked | **run only** (closed box), never committed |
| *Gimmick!* (Sunsoft) | commercial ROM | **run only**, from the player's set via the environment, never committed |
| Icarus Verilog, oss-cad-suite | GPL / ISC (tools) | **tool**; running it does not touch our licence |
