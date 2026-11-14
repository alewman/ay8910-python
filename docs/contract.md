# The contract: the chip's bus, its time and its outputs

This is what a host can rely on and what a port must reproduce. Everything here is
checked by `tests/` or by the conformance kit ([conformance.md](conformance.md));
how strongly each behaviour is known is [claims.md](claims.md).

## One chip, five parts

```python
from ay8910_python import PSG, AY8910, AY8912, AY8913, YM2149, SUNSOFT_5B

chip = PSG(YM2149)  # an Atari ST's
chip = PSG(SUNSOFT_5B, record=False)  # Gimmick!'s, polled by its board
```

The part is a constructor argument, a `PSGVariant`: a value, not a subclass, so a
host can build its own. Every part runs the same engine; the fields are the only
differences.

| Field | `AY8910` | `AY8912` | `AY8913` | `YM2149` | `SUNSOFT_5B` |
| --- | --- | --- | --- | --- | --- |
| `envelope_steps` | 16 | 16 | 16 | 32 | 32 |
| `codes` (DAC levels) | 16 | 16 | 16 | 32 | 32 |
| `ports` bonded out | A, B | A | none | A, B | none |
| `register_masks` (bits kept and read back) | the register's width | the same | the same | all eight | all eight |
| `clock_divider` at power-on | 1 | 1 | 1 | 1 | 2 |
| `has_sel_pin` (the divider can be changed) | no | no | no | yes | no |
| `dac` | measured | measured | measured | measured | Yamaha's ladder |

`VARIANTS` maps each part's `name` to it.

## Time

The core counts **input clocks**, the CLOCK pin: 1,789,773 Hz on an NTSC Famicom
(the 5B takes the CPU's clock), 1,773,400 Hz on a Spectrum 128, 2 MHz on an Atari
ST, 1,789,772.5 Hz on an MSX.

- **`tick()`** is one input clock and **`run(clocks)`** that many. `clock` counts
  them since /RESET. A board that polls calls `tick()` each cycle: on PyPy a call
  of `run(1)` from a hot loop costs several times a `tick()`.
- A part with `clock_divider` 2 moves on every second input clock. The host
  never divides anything itself. On a YM2149, `chip.clock_divider = 2` is the
  /SEL pin taken low.
- The chip divides by eight inside (`CLOCKS_PER_STEP`): a tone of period `TP` is
  high for `8·TP` internal clocks and low for as many (`f = clock / (16·TP)`);
  the noise steps every `16·NP`; an envelope ramp lasts `256·EP` on every part,
  in 16 steps or 32. A period of 0 behaves as 1, on all three.
- **The host owns the conversion**, and brings the chip up to the moment of each
  write or read with `tick()` or `run()` first. A write is an instant between two input
  clocks.

## Power-on

`PSG()` and `reset()` are the /RESET pin: every register 0 (all tones and noise
enabled, both ports inputs, volumes 0: silence), the tones high, the noise
register empty, the divider at the start of its eight, the address latch
deselected. `clock` reads 0 and the output queue is empty.

## The bus

| Bus function | API | Behaviour |
| --- | --- | --- |
| latch address | `select(value)` | The low four bits name the register. The high four must be 0; any other byte deselects the chip until the next good one, and leaves the latch alone. On the 5B this is a write to $C000-$DFFF. |
| write | `write(value)` | To the selected register; nothing if deselected. The register keeps the bits `register_masks` allows. On the 5B, $E000-$FFFF. |
| read | `read()` | The selected register. Registers 14 and 15 return their port's pins. $FF if deselected (the chip is not driving the bus: a board with its own open bus checks `selected`). |
| both | `write_register(r, v)`, `read_register(r)` | An address byte and a data byte together; and what a read of `r` returns, without moving the latch. |

What a write changes, and when:

- **Tone, noise and envelope periods** (0-5, 6, 11-12) are compared at the next
  strobe, once every eight internal clocks. They restart nothing. Written in the
  clock after the strobe, they are compared at once.
- **The mixer** (7) and **the volumes** (8-10) change the output at once. Bit 4 of
  a volume gives the channel to the envelope.
- **The shape** (13) restarts the envelope, whatever is written: bit 3 continue,
  2 attack, 1 alternate, 0 hold.
- **The ports' latches** (14, 15) and their directions (7, bits 6 and 7; 1 is
  output).

An AY's registers have only their own bits; read after an address byte, the rest
are 0. Read straight after a write with no address byte between, they are the
byte just written (the chip's internal bus still holds it). A Yamaha part
returns every bit as written.

## The ports

A port is eight pins, so it is two callables the board supplies, each optional:

```python
chip.port_a_in = lambda: keyboard_row()  # the levels the outside drives; unset: $FF
chip.port_a_out = set_mapper_lines  # called with the levels the chip drives
```

- An input port reads the outside's levels; with no `port_a_in`, its pull-ups: $FF.
- An output port drives its latch, and a read returns the pins: the latch ANDed
  with what the outside drives.
- `port_a_out(value)` is called when what the chip drives changes: the latch
  while the port is an output, $FF while it is an input.
- A port that is not bonded out (`ports`) is never asked and never told; its
  register still stores, and reads as pull-ups or as its latch.

## The outputs

| Output | API | What |
| --- | --- | --- |
| the digital state | `levels()` | `(a, b, c)`: the DAC code each channel drives now, 0-15 on an AY and 0-31 on a Yamaha part. A channel drives its volume, or the envelope's level, while (tone OR tone disabled) AND (noise OR noise disabled), and 0 otherwise. A Yamaha volume `v` is code `2v + 1`. This is what the referee compares, at every clock. |
| per clock | `take_outputs()` | One `levels()` per input clock run, each the state after that clock; then cleared. Only with `record=True` (the default). |
| a level | `mix()` | The three codes through `variant.dac`, added: 0.0-3.0. |
| per clock | `take_samples()` | `take_outputs()` as `mix()` values. |

A board that polls calls `tick()` and `levels()` or `mix()` each cycle and
constructs the chip with `record=False`, so nothing is queued. The two `take_`
methods drain the same queue.

`variant.dac[code]` is the pin's level for a code, 0.0 to 1.0. The analogue path
after the pins (the load three tied outputs share, the DC level, filters, the 5B's
amplifier, resampling to the host's rate) belongs to the board.

## What a port must reproduce

The codes at every input clock, the bytes read and the levels driven on the
ports, over the conformance examples ([conformance.md](conformance.md)). The DAC
tables are data a port copies; `tests/test_variants.py` checks them here.
