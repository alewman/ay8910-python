# Re-derived: four behaviours, from the pins and the documents

Written 2026-11-14 for wave 2, item 3 of the family provenance audit
([provenance.md](provenance.md), "The rewrite, and the alternative"). The audit
found four behaviours of the engine whose first source was the GPL-3.0 AY model's
text, read while the engine was written. Each is re-established here from sources
the charter allows, by a session that did not open `ay_model.v`, `fmopn.c` or the
flagged parts of the old `chip.py` (those ranges were blanked by a script before
the file was read; the old file is kept, unread, in the git-ignored `trash/`). The
engine's code for the four was then written again from this file and the
documents alone.

## Tags

- **DOC**: a manufacturer document. GI's *AY-3-8910/8912/8913 Programmable Sound
  Generator* data sheet (`reference/docs/generalinstrument_ay-3-8910.pdf`, pages
  cited as printed, 5-18 to 5-25); Yamaha's YM2149 catalog LSI-2121492.
- **HARDWARE**: a statement in prose that a real chip was tested, with its source.
- **MEASURED (closed box)**: what the pins of lvd's Verilog model of deathsoft's
  AY-3-8910 die schematic show, run under Icarus Verilog as `ay_ref`
  (lvd2/ay-3-8910_reverse_engineered @ cf8d14d, GPL-3.0; Icarus 14.0 devel from
  oss-cad-suite 2026-10-05), driven only at its pins by `validation/ay_tb.v`. The
  model was built with the repository's existing script and never opened. Its
  verdicts are the *model's*, a transcription of a drawing of the die, not a
  measurement of a chip.

## How the probes were made

`scripts/probe_die.py` (run as `PYTHONPATH=src:scripts python scripts/probe_die.py
--json FILE`) writes short streams of bus events, runs them through `ay_ref`, and
prints what the pins show. Every probe starts from /RESET. A time `t` is input
clocks after /RESET is released; an event at `t` lands before clock `t`'s rising
edge (in the clock's low half), and sample `t` is the pins after clock `t`. The
streams of `scripts/streams.py` (24 of them, 25.7 million clocks, seeded writes,
reads, pins and resets of every kind) then compare the rewritten engine with the
model at every clock: they are the wider measurement, the probes the readable one.

---

## 1. The divider's eight: the strobe, the count, the held counter, the open strobe

### What the pins show

**a. Edges fall on one clock of eight.** A tone of period P written at clock 0
changes level at clocks (MEASURED, `tone_after_reset`):

| P | edges |
| --- | --- |
| 0 | 10, 18, 26, 34, ... |
| 1 | 10, 18, 26, 34, ... |
| 2 | 18, 34, 50, ... |
| 3 | 26, 50, 74, ... |
| 4 | 34, 66, 98, ... |

Every edge of every tone in every probe and stream falls on a clock `t` with
`t mod 8 = 2`, so the clock is divided by eight (DOC: "counting down the input
clock by 16", page 5-21, is the eight and the toggle) and the decision to change
is taken once a turn, on the third clock of each eight after /RESET. This is
**STROBE_PHASE = 2**.

**b. A counter that has just expired, or come out of /RESET, cannot expire at the
next strobe.** Period 0 gives the same edges as period 1, 8 clocks apart, never
every clock, and the first edge after /RESET is at clock 10, not at the strobe of
clock 2 (table above). The noise and the envelope do the same: at period 0 and
period 1 from clock 0 their first changes are identical (noise at 274 and 290;
envelope steps at 18, 34, 50, ...), and at period 2 the envelope steps at 34, 66,
98 (MEASURED, `held_after_reset`). HARDWARE: the NESdev wiki's "Period 0
verification" (rainwarrior, a real *Gimmick!* cartridge) finds period 0 equal to
period 1 for the tone, the noise and the envelope.

**c. A period shortened under a running count ends the half-cycle at the next
strobe; once written in the clock after a strobe, at once.** A tone of period 40
has an edge at E = 322. Period p is written at clock E + d (MEASURED,
`tone_period_writes`, d = 1-96, p = 1-13). The next edge comes at:

- E + 8m, the first strobe at which m >= p, when the write lands at or before that
  strobe's clock (writes at d = 1-8 with p = 1 give the edge at E + 8; d = 10-16
  give E + 16);
- **E + d itself**, when the write lands on the clock after a strobe (d = 9, 17,
  25, ...: `d mod 8 = 1`, the clock with phase 3) and the count the strobe just
  saw already reaches p. At d = 9, p = 1 edges at E + 9; at d = 17, p = 1 and 2
  edge at E + 17 but p = 3 waits for E + 24. The value compared in that clock is
  the one the strobe saw, m, not m + 1.

HARDWARE for the first half: the wiki's "Phase counting verification" (a period
shortened mid-cycle ends the half-cycle early, it does not wrap round).

**d. A counter is released and counts in the same clock.** After the edge at E,
period 0 written at E + 1 (the clock after the strobe that expired the counter)
does not edge at E + 1: the expired counter is not compared. Period 0 or 1
written at E + 9 edges at once (c) and again at E + 16, seven clocks later, not
fifteen: the count of that same clock (phase 3) started the new half-cycle
(MEASURED, `tone_open_strobe`). The count that follows an expiry or /RESET both
lets the counter be compared again and counts it to 1: after an edge at E with
period p, the next is at E + 8p, so p counts lie between (a: periods 1-4).

**e. The same rules hold for the envelope's counter.** Envelope period 20
restarted at clock 0; period p written at clock w. The first step lands on a
strobe after the counter reaches p, except that p = 1 written at clock 171 (phase
3, after the strobe at 170 saw the counter at 1) steps at 171 itself (MEASURED,
`envelope_period_writes`). The noise's counter is held to the same rules by the
streams `noise_periods`, `noise_period_changes` and `noise_sequence`, which equal
the model at every clock with one counter machine for all five counters.

### The fact, restated as the engine's rules

The divider counts eight internal clocks from /RESET, phases 0-7. On **phase 2**
(the strobe) every counter that is not held is compared with its period, and one
that has reached it (count >= period) expires: it is cleared and held. On **phase
3** every counter counts by one and every hold is released. A period written
between the strobe's clock and the next (so before the clock of phase 3) is
compared with the counter at once, as at the strobe, before that clock's count.
/RESET clears and holds every counter. Where the count falls inside the eight is
seen only through the open strobe and the envelope's restart (item 2: the
restart's behaviour changes between a write before the clock of phase 3 and a
write after it), so **COUNT_PHASE = 3**.

Tag: **MEASURED (closed box)**, model @ cf8d14d; period 0 as 1 and phase counting
also **HARDWARE** (wiki). The eight itself: **DOC**.

---

## 2. The envelope's restart in the two halves of the eight

### What the pins show

Envelope period EP, shape $08 (repeating decay), written at clock 0 (the first
restart); then the shape written again at clock `at`. Answer: clocks from the
second write to the first step, 15 to 14 (MEASURED, `envelope_restarts`, EP 0-5,
every clock over two full step periods). The write always puts the level back at
15 at once.

| EP | write before the clock of phase 0-3 | write before phase 4-7 |
| --- | --- | --- |
| 0, 1 | `(3 - phase) mod 8 + 15` (18, 17, 16, 15) | 14, 13, 12, 11 |
| 2 | 34, 33, 32, 31 | 30, 29, 28, 27 **or** 38, 37, 36, 35 |
| 3 | 50 ... 47 | 46 ... 43 **or** 54 ... 51 |
| 4 | 66 ... 63 | 62 ... 59 **or** 70 ... 67 |
| 5 | 82 ... 79 | 78 ... 75 **or** 86 ... 83 |

Read as counts: a write before the count (phases 0-3) is followed by `2·EP` counts
and the strobe after the last one, wherever the counter stood: the counter was
cleared and held. A write after the count (phases 4-7) is followed by `2·EP - 1`
counts or by `2·EP`; which one follows the counter's value when the write landed
(it is fixed by the clocks since the first restart). Counting the old counter
forward (a count on every phase 3, cleared at every expiry), every case with
`2·EP - 1` counts had an **odd** counter and every case with `2·EP` an **even** one,
over all 240 writes in the second half at EP 2-5. So a restart after the count
keeps the counter's lowest bit and clears the rest.

**Not held after the count.** Envelope period 4, restarted at 0; at clock `at`
period 0 is written and the shape at once (MEASURED, `envelope_restart_period_0`).
Before phases 0-3: first step 18, 17, 16, 15 clocks later (the counter is held over
the strobe of phase 2, so period 0 cannot expire there). Before phases 4-7: 14,
13, 12, 11, with the counter even (at 28: 4) as with it odd (at 20: 3). An even
counter cleared to 0 and held would give 22-19. So after the count the cleared
counter is compared at the next strobe, and period 0 expires at it.

**The rest of the restart.** The first step comes on the second expiry after the
write in every case above, so the 16-step envelope's halving is restarted too; the
level is the ramp's start at once; shape $09 held at 0 and written again goes back
to 15 and steps down (MEASURED, `envelope_restart_releases_hold`). HARDWARE: the
wiki's "Envelope phase reset verification" (any write to the shape register
restarts the envelope).

### The fact, restated as the engine's rules

A write to the shape register restarts the envelope: the step, the halving and
any hold are cleared and the level goes to the ramp's start. The period counter
is cleared and held until the count if the write lands before the clock of phase
3 has run in the current eight (phases 0-3); after it (phases 4-7) the counter
keeps its lowest bit, loses the rest, and is not held.

Tag: **MEASURED (closed box)**, model @ cf8d14d, **and nothing else**. No hardware
statement covers the second half; on the die it is dynamic logic the model reads
one way. A real chip measured at its pin (claims.md, "Open") would settle it.

### Default or variant

Kept as the default of every part. The audit offered a non-default variant row,
as pokey-python did for its model-only U19 and U20. That was not done here,
because (a) the alternative would have to be invented (no source says what a
real chip does instead), (b) every one of the 132.9 million board-stream clocks
and the 24 synthetic streams agree with it, and the audit's own standard keeps a
closed-box measurement as a source, and (c) moving it changes a step by 8 clocks
in some restarts, nothing a listener hears. It is marked in claims.md as the
model's reading, measured closed-box, with no hardware behind it. Whether it
should leave the default is Aubrey's call.

---

## 3. Unused register bits on read-back

### What the pins show

MEASURED, `read_back`. Every register 0-13 was written with $FF, $00, $A5 and $5A
by an address byte and a data byte, then read with no address byte between (a
"bare" read), then read again after an address byte:

| Register | width | bare read after the write | read after an address byte |
| --- | --- | --- | --- |
| 0, 2, 4, 7, 11, 12 | 8 bits | the byte written | the byte written |
| 1, 3, 5, 13 | 4 bits | the byte written | its low 4 bits, the rest 0 |
| 6, 8, 9, 10 | 5 bits | the byte written | its low 5 bits, the rest 0 |

And in sequence (R1 written with $B7 each time):

| Sequence | Read |
| --- | --- |
| write, bare read | $B7 |
| then a second bare read | $B7 |
| then an address byte, read | $07 |
| then a bare read | $07 |
| write, 20,000 clocks, bare read | $B7 |
| R1 <- $B7, a deselecting address byte ($11), a data byte $55, address 1, read | $07 |
| R0 <- $C3, address 1, read R1 | $07 |

So the unused bits read what the chip's internal data bus last carried: the byte
of the last data write, or 0 after an address byte (whose high bits are always 0
when it selects the chip). A read changes nothing a later read can see. The
model keeps it for ever (the 20,000-clock case): its bus is a charge-keeping net
with no leak.

HARDWARE: MAME's ay8910.cpp (BSD-3-Clause, @ 518bb5e), the comment over the read
masks: "Tested and confirmed on hardware: AY-3-8910: inaccessible bits (see masks
below) read back as 0". Its masks are the widths above. It does not say whether
an address byte came between; a host reading a register in the ordinary way sends
one first, and then the model and the hardware statement agree.

### Which was kept

The model's behaviour, measured closed box. It contains MAME's hardware statement
as the case that statement covers (address byte, then read), and the 24 streams
compare reads at every clock with it (`registers_read_back`, `address_latch`, the
seeded `random_*` streams). Replacing it with "always 0" would make the core
differ from the model on every bare read after a write, with no hardware
measurement saying the model is wrong there. What a real chip returns on a bare
read some time after a write (the charge leaks in a time the model does not have)
is not known and stays open.

Tag: the widths and "0 after an address byte" **HARDWARE** (MAME's statement) and
**MEASURED**; "the last data byte, with no address byte between" **MEASURED
(closed box)** only. DOC: "Each of the 16 registers within the PSG is also
readable" (page 5-19).

---

## 4. A port's read returns its pins, in either direction

### What the documents say

- DOC, page 5-19: "Each pin is provided with an on-chip pull-up resistor, so that
  when in the 'input' mode, all pins will read normally high. Therefore, the
  recommended method for scanning external switches would be to ground the input
  bit." An input port's read is its pins, high unless the outside pulls them low.
- DOC, page 5-22: R16 and R17 "function as intermediate data storage registers
  between the PSG/CPU data bus and the two I/O ports".
- MAME ay8910.cpp (BSD-3-Clause), over its port read: "even if the port is set as
  output, we still need to return the external data. Some games, like kidniki,
  need this to work", and "The io ports are designed as open collector outputs".
  This is an observation of game software (OBSERVED), not a stated chip test.

### What the pins show

MEASURED, `port_reads`. Latches $12 (A) and $34 (B); the outside drives $5A and
$C3 while the ports are inputs (the testbench leaves the pins alone while a port
is an output: against the model's drivers its answer would be X).

| State | Read A | Read B | Pins A, B |
| --- | --- | --- | --- |
| inputs | $5A | $C3 | $5A, $C3 |
| outputs | $12 | $34 | $12, $34 |
| output, A's latch rewritten $9E | $9E | | $9E, $34 |
| inputs again | $5A | $C3 | $5A, $C3 |

An input port reads the outside's levels, not its latch, which it keeps: made an
output again it drives the latch. An output port reads what is on its pins, which
with no one fighting it is its latch.

### The fact, restated

A read of register 14 or 15 returns the port's pins: as an input the outside's
levels (the pull-ups' $FF if nothing drives them); as an output the levels on the
pins, which the core takes as the latch ANDed with the outside (phase0.md decision
8: the pull-ups and GI's "ground the input bit" make the outside win low; no judge
decides a fight). A port the part does not bond out has no outside: as an input it
reads its pull-ups, as an output its latch.

Tag: input **DOC** and **MEASURED (closed box)**; output, unfought **MEASURED
(closed box)**, with MAME's game observation agreeing; output fought **decided
here** (unchanged).

---

## What the engine's rewrite changed

The rules above are what the old engine was recorded as doing (claims.md,
validation.md), and the rewritten engine follows them, so nothing at the pins was
meant to change. The comparison bears it out: docs/validation.md, "Re-derivation
of 2026-11-14".
