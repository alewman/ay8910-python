# Claims: what is known, how strongly, and by what

Tiers ([validation.md](validation.md)): **hardware** (a measurement of a real
chip), **die-derived** (a transcription of the silicon), **manufacturer** (a data
sheet), **emulator** (another program: evidence only). "5B hardware" is
rainwarrior's tests on a real *Gimmick!* cartridge, as the NESdev wiki records
them (Sunsoft_5B_audio.wiki, each with its forum post).

## The AY parts

| Claim | Tier | Evidence |
| --- | --- | --- |
| The register map, the bus functions, the address byte's chip-select bits, the pull-ups | manufacturer | GI's data sheet; Yamaha's catalog has the same |
| The clock is divided by eight; one strobe a turn compares every counter, and they count on the next clock | die-derived (closed box); manufacturer for the eight | every input clock of 24 synthetic streams and 7 programs equals the die model; the probes of [rederived.md](rederived.md), item 1 |
| Counters count up and expire at "count >= period"; a counter is held at 0 from its expiry until the count, so period 0 is period 1 for tone, noise **and envelope** | die-derived (closed box); 5B hardware agrees | the same; rederived.md, item 1 b, d; the wiki's "Period 0 verification" for all three |
| Shortening a period under a running count ends the half-cycle at the next strobe, and at once if written in the clock after the strobe | die-derived (closed box); 5B hardware for the first half | `tone_period_changes`; rederived.md, item 1 c, e; the wiki's "Phase counting verification" |
| Nothing restarts a tone or the noise; no generator can be halted | die-derived; 5B hardware | no reset path in the die but /RESET; the wiki's "No halt verification" |
| The noise is a 17-bit register shifting left, fed bit 16 XOR bit 13, stepping on every second expiry of its counter, heard inverted at bit 16; empty after /RESET, it takes in a 1 | die-derived; 5B hardware for the taps | `noise_sequence` (the whole 131,071 steps); the wiki's "LFSR verification"; MAME's "verified on AY-3-8910 and YM2149 chips" for the same pair mirrored |
| The sixteen envelope shapes; a 16-step ramp stepping on every second expiry | die-derived; manufacturer | `envelope_shapes`; GI's Fig. 1 |
| Any write to the shape register restarts the envelope | die-derived; 5B hardware | `envelope_restarts`; the wiki's "Envelope phase reset verification" |
| A restart in the second half of the divider's eight leaves the period counter's lowest bit and does not hold the counter, so the first step comes 8 clocks sooner or later than a count from 0 | **measured on the die model only** (closed box): its reading of dynamic logic | `envelope_restarts`, `envelope_periods`; rederived.md, item 2 (240 of 240 restarts follow the counter's lowest bit). No hardware statement or measurement covers it |
| The mixer: (tone OR disabled) AND (noise OR disabled); volume and mixer act at once | die-derived; manufacturer | `mixer_and_volume` |
| A register keeps only its own bits and the rest read 0 after an address byte | die-derived (closed box); hardware | `registers_read_back`; rederived.md, item 3; MAME ay8910.cpp (BSD-3-Clause), the comment over its read masks, "Tested and confirmed on hardware" |
| ...and read back the byte just written when no address byte came between | die-derived (closed box), **charge on the model's bus** | `address_latch`; rederived.md, item 3; a real chip's charge leaks away in a time the model does not have |
| An address byte with DA7-DA4 not 0 deselects the chip until the next good one | die-derived; manufacturer | `address_latch`; both data sheets |
| A port's read returns its pins; an input port is the outside's, pulled up | die-derived (closed box); manufacturer | `ports`; rederived.md, item 4; GI's data sheet ("when in the 'input' mode, all pins will read normally high"); MAME's prose (an output port's read must return the outside's data for *Kid Niki*) |
| An output port's pins are its latch ANDed with the outside | **decided here** | no judge: the die model answers X (phase0.md, decision 8) |
| /RESET: registers 0, tones high, noise register empty, the divider at the start of its eight | die-derived | `resets`, on every phase |
| The AY-3-8912 and 8913 are the 8910's die with fewer pins | manufacturer | GI's data sheet (one sheet, three pinouts); not judged separately |

## The Yamaha parts

| Claim | Tier | Evidence |
| --- | --- | --- |
| A 32-step envelope stepping on every expiry; a volume `v` drives code `2v + 1` | manufacturer; die-derived (YM2203); 5B hardware | Yamaha's catalog, section (4)-(6) and Fig. 1; 208 cases against YM2203-LLE; the wiki's "Envelope-Volume equivalence verification" |
| Every tone, noise and envelope period's rate; all sixteen shapes level by level; the noise register's sequence; the mixer's gates | die-derived (YM2203) | the same 208 cases, run for run |
| Period 0 is period 1, envelope included | die-derived (YM2203); 5B hardware | the same; the wiki |
| Halved to sixteen codes, everything equals the AY's die at every clock | die-derived (AY) | the synthetic streams and the 5B programs, on the 5B and YM2149 variants |
| /SEL low halves the clock; the 5B is a YM2149 with /SEL low | manufacturer; 5B hardware | Yamaha's catalog, pin 5; the wiki, "Sound" |
| The YM2149 keeps and returns all eight bits of every register | hardware (reported) | MAME ay8910.cpp (BSD-3-Clause), "YM2149: no anomaly"; not judged here (the YM2203 harness has no read path) |
| Codes 0 and 1 are both silence | 5B hardware; die-derived (YM2203, closed box) | the wiki, "Tone" and "Envelope"; one 32-step ramp of the YM2203's die model shows 31 levels, the lowest 0, which volume 0 drives (`ssg_referee.py`, `die_levels`) |
| **When inside a step a write takes hold; the restart's exact first step; which input clock the halved clock ticks on** | **unverified** | the AY's machine, on trust (phase0.md, decision 1) |

## The DAC tables

| Table | Tier | Source |
| --- | --- | --- |
| `DAC_AY_MEASURED` (the AY parts' default) | hardware | Matthew Westcott's voltages from a ZX Spectrum 128's pin, 2001, public domain (quoted in MAME ay8910.cpp:681-716), normalised. ayumi's AY table, another measurement, is within 6.3% of it at every level |
| `DAC_AY_LOGARITHMIC` | reasoning | 3 dB a step. GI's sheet says only "logarithmic steps" (Fig. 3, no numbers) |
| `DAC_YM_MEASURED` (the YM2149's default) | hardware | ayumi's `YM_dac_table` (MIT) |
| `DAC_YM_DATASHEET`, `DAC_5B` (the 5B's default) | manufacturer; 5B hardware | Yamaha's Fig. 1 (1, .841, .707, .595, .5 ...: the fourth root of two a step); the wiki's 1.5 dB a step with 0 and 1 silent |

The measured AY levels sit above the 3 dB ladder everywhere below the top, by up
to 4.8 dB; the measured YM2149 levels within 2.6 dB of Yamaha's from code 4 up
(`tests/test_variants.py`). A pin's level also depends on its load, and three pins
tied together load one another: MAME models that with resistor networks
(ay8910.cpp:619-726). That is the board's circuit, not the chip's.

## Where the judges disagree

Recorded, not settled by picking.

1. **Envelope period 0.** The AY's die: as period 1 (`envelope_periods`). The 5B's
   hardware: as period 1 (the wiki). The YM2203's die: as period 1. **MAME** for
   its AY type: twice as fast as period 1 (ay8910.cpp:89-91, "this does NOT apply
   to the Envelope period", and line 1119, `period * m_step`). The core follows
   the two dies and the hardware.
2. **The envelope's restart.** After a shape write the AY's die takes its first
   step `2·EP` counts later for a 16-step part, give or take the count the
   lowest-bit rule moves it; on a 32-step part the core therefore shows its first
   audible change `2·EP - 1` or `2·EP` counts after the write. The YM2203's die
   shows it `2·EP + 1` counts after, always (`scripts/ssg_referee.py
   --restarts`). **MAME** does not clear the period counter on a shape write at
   all (`set_shape`, ay8910.h:243-260), so its first step comes anywhere within
   a period. Which of the dies a real YM2149 follows is open; the core has the
   AY's.
3. **A period shortened below the count.** The dies clear the counter when it
   expires. **MAME** subtracts the period and keeps the remainder
   (ay8910.cpp:1082), so its next half-cycle is shorter.
4. **The noise's polarity and start.** The die hears the register's top bit
   inverted and starts from an empty register that takes in a 1; **MAME** hears
   its bit uninverted and starts from 1 (ay8910.h:284, ay8910.cpp:1309). The
   sequence is the same one; where it starts and which way up it is are not.
5. **Tone and noise together.** How a tone and the noise line up on a Yamaha
   part is not judged: the YM2203's machine serves them in another order, and
   the two waveforms ANDed depend on it (`scripts/ssg_referee.py` leaves such
   channels out).
6. **Unused register bits on a Yamaha part.** MAME reports the YM2149 returning
   them as written. The YM2203's read-back was not measured here (the harness
   has no read path), and it is another chip; the core's YM2149 follows the
   report about the YM2149.

## Open

- The Yamaha parts' timing inside a step, and so every clock-exact claim about
  them (phase0.md, "Open questions").
- A write strobe's width and place. On the die the registers are open and the
  envelope held in reset for as long as the strobe lasts; the core's write is an
  instant, and the bench puts it in the clock's low half, before the rising
  edge. A strobe in the high half, or one lasting several clocks (a Z80's does),
  was not put to the die model; the rules that depend on the clock a write lands
  in (the open strobe, the restart's two halves) may shift by a clock for such a
  bus.
- The lowest-bit rule of the envelope's restart and the charge on the internal
  bus are the die *model's* reading of dynamic logic, measured at its pins
  (rederived.md, items 2 and 3). No measurement of a real chip was checked for
  either.
- The analogue outputs: the DC level (about 2 V on a YM2149, Yamaha's catalog),
  the load, and on the 5B the amplifier and its compression above volume 14
  (the wiki, "Output").
- The test pins.
