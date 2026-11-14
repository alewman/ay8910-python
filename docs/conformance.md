# Conformance: proving another core is the same chip

This page is for someone writing this chip in another language (the family's Rust
transcription first) who wants to use this core as the reference. The tooling is
`ay8910_python.conformance`; the shape is the family's, after sn76489-python's and
ym2413-python's kits.

## What must match

At every input clock, the three channels' DAC codes; in order, every byte read;
and the levels the chip drives on its ports. That is the whole of the chip's
digital behaviour at its pins. The DAC tables are data to copy.

## The manifest

A JSON object, version 1:

```json
{
 "version": 1,
 "name": "tones-ay-3-8910",
 "variant": "AY-3-8910",
 "clocks": 4175,
 "events": [
  [16, "write", 7, 56],
  [16, "write", 8, 15]
 ]
}
```

An event is `[t, kind, a, b]`, applied when `t` input clocks have run (before
clock `t`, counting from 0). Events are in clock order; those with the same `t`
apply in the order given.

| Kind | `a` | `b` | What |
| --- | --- | --- | --- |
| `write` | register | value | an address byte, then a data byte |
| `read` | register | 0 | an address byte, then a read |
| `select` | byte | 0 | the address byte alone (its high bits may deselect) |
| `data` | 0 | value | a data byte alone, to whatever is selected |
| `read_data` | 0 | 0 | a read alone |
| `reset` | 0 | 0 | /RESET |
| `pins_a`, `pins_b` | levels | 0 | what the outside drives onto the port's pins from now on ($FF at the start) |
| `divider` | 1 or 2 | 0 | the /SEL pin (a YM2149 only) |

## The trace

Text, version 1, one record a line:

```text
# ay8910-trace 1
# tones-ay-3-8910 AY-3-8910
L 0 0 0 0
P 0 255 255
L 19 15 9 4
L 27 0 0 4
...
# end 4175 clocks 86 events
```

- `L clock a b c`: the codes after input clock `clock` (counted from 1; `L 0` is
  the state out of /RESET). Written whenever the codes differ from the last `L`
  line's. A write changes the output at once, but an `L` line is the state *after
  a clock*: a write before clock 17 shows on `L 17` at the earliest.
- `R clock value`: a byte read, with `clock` input clocks run. A read from a
  deselected chip is 255.
- `P clock a b`: the levels the chip drives on ports A and B (255 for an input),
  at the start and whenever an event changes them.
- `# end`: the clocks run and the number of events.

/RESET does not restart the trace's clock.

## The examples

`examples/conformance/` holds 19 manifests with their traces, made by
`scripts/make_examples.py`:

| Example | What it holds a port to |
| --- | --- |
| `tones-ay-3-8910` | periods 0-7; a period shortened under a running count on each phase of the divider (the open strobe) |
| `noise-ay-3-8910` | noise periods 0, 1, 2, 5: the register's taps, its halved rate, its inverted output |
| `envelope-shapes-ay-3-8910`, `-ym2149` | all sixteen shapes, 16 and 32 steps |
| `envelope-restarts-ay-3-8910` | the shape rewritten on every phase under odd and even counts, periods 0-3 |
| `mixer-ay-3-8910` | every mixer value over tone, noise and envelope |
| `registers-ay-3-8910`, `-ym2149` | read-back widths, the internal bus's charge, deselecting address bytes |
| `unused-bits-ym2149` | a Yamaha part keeps unused bits and its sound ignores them |
| `ports-ay-3-8910`, `-8912`, `-8913` | ports as inputs and outputs, bonded out or not |
| `port-contention-ay-3-8910` | an output port's pins pulled low from outside |
| `reset-ay-3-8910` | /RESET on each phase of the divider |
| `sunsoft-5b` | the halved clock, the volumes' codes, noise, three envelope shapes |
| `sel-pin-ym2149` | the divider changed under a running tone and envelope |
| `random-walk-ay-3-8910`, `-ym2149`, `-sunsoft-5b` | 260 seeded writes each |

Seventeen were put to the AY-3-8910's die model before they were written
(`make_examples.py --judge`): the AY-3-8910's whole, the other parts' on their
codes (a Yamaha part's halved, as the die can judge them). Two are this core's word
alone: `sel-pin-ym2149` (the AY has no such pin) and `port-contention-ay-3-8910`
(the die model answers X). In the judged runs the die's data pins are pulled low,
so its read of a deselected chip is 0 where the trace says 255.

## Running it

```text
ay8910-conformance trace examples/conformance/tones-ay-3-8910.json > port.trace
ay8910-conformance diff examples/conformance/tones-ay-3-8910.json port.trace
ay8910-conformance check examples/conformance
```

`diff` prints the first line that differs and exits 1; `check` runs every example
against the trace beside it.

## What a port may claim

- **The examples pass**: the port is this core on 19 runs chosen to break the
  mistakes a port makes. Of 61 seeded faults in this core, the examples alone
  catch 58 (`scripts/mutation.py --examples-only`); the three they miss are two
  errors in the DAC tables, which a trace of codes cannot see, and a latch that
  moves on a deselecting address byte, which nothing at the pins can see.
- **Equal to this core on the referee's streams** (`scripts/streams.py`, and a
  board's streams): the port inherits this core's claims
  ([claims.md](claims.md)), no more: in particular the Yamaha parts' timing
  inside a step is the AY's, on trust.
