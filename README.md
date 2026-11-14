# ay8910-python

A readable, pure-Python reference core of General Instrument's **AY-3-8910**
programmable sound generator and its relatives: the **AY-3-8912** and **8913**
(the same die in fewer pins), Yamaha's **YM2149** (a 32-step envelope and a pin
that halves the clock) and the sound half of **Sunsoft's 5B** (*Gimmick!*: a
YM2149 with the clock halved). Three square-wave tones, a noise generator, an
envelope generator, a mixer, two I/O ports and sixteen registers behind an
address latch.

It is not a programmer's-model PSG. It is the AY's **machine**: a divide-by-eight,
one strobe a turn that asks five up-counters whether they have reached their
periods, registers that are open latches, and the odd corners that follow (a
period of 0 is a period of 1 because a cleared counter is held until it counts; a
shorter period written in the strobe's clock takes hold at once; an envelope
restarted in the wrong half of the divider keeps its counter's lowest bit). At
**every input clock** of the streams below, the three channels drive what the
AY-3-8910's die drives. What differs between the parts is data on a `PSGVariant`,
not branches.

It is a chip in the family's shape (chips are cores, boards compose cores), beside
[sn76489-python](https://github.com/alewman/sn76489-python),
[ym2413-python](https://github.com/alewman/ym2413-python) and
[ym2612-python](https://github.com/alewman/ym2612-python). Its first board is
famicom-python (mapper 69's 5B); the MSX, the Spectrum 128, the CPC, the Atari ST
and arcade boards come after.

## Validation

| What | Result | Tier |
| --- | --- | --- |
| The three codes at every input clock (on the AY-3-8910 also the sixteen port pins and every read) against lvd's model of the AY-3-8910's die @ cf8d14d: 24 synthetic streams | **25,725,326 clocks, 0 different**, on each of the five parts (the Yamaha parts' codes halved) | die-derived (the judge) |
| The same, the 5B's writes recorded from famicom-python: *Gimmick!* and six of rainwarrior's 5B test programs | **132,911,140 die clocks, 0 different**, as an AY-3-8910 and as the 5B | die-derived |
| The Yamaha parts' waveforms against the SSG of the YM2203's die (YM2203-LLE @ 817387f): every period, all 16 shapes and 32 levels, the noise, the mixer | **208 cases, 866,618 steps each, 0 different** | die-derived, one chip removed |
| The same die on *when* a write takes hold | differs (the envelope's restart, one or two counts) and is not the AY's machine | recorded: [docs/claims.md](docs/claims.md) |
| 61 seeded faults | 61 caught by the tests; 58 by the 19 conformance examples alone | not an oracle |

What each result supports, and what is **unverified** (the Yamaha parts' timing
inside a step: no YM2149 die is published), is [docs/claims.md](docs/claims.md).
The runs are [docs/validation.md](docs/validation.md); the API is
[docs/contract.md](docs/contract.md); a port proves itself with
[docs/conformance.md](docs/conformance.md); the sources, the decisions and the
open questions are [docs/phase0.md](docs/phase0.md).

## Minimal host

```python
from ay8910_python import PSG, YM2149

CLOCK = 2_000_000  # an Atari ST's

chip = PSG(YM2149)
chip.write_register(7, 0x3E)  # tone A alone
chip.write_register(0, 284 & 0xFF)  # 2,000,000 / (16 * 284) = 440 Hz
chip.write_register(1, 284 >> 8)
chip.write_register(8, 15)  # full volume
chip.run(CLOCK // 10)  # a tenth of a second
codes = chip.take_outputs()  # [(a, b, c), ...], one per input clock, 0-31
levels = [YM2149.dac[a] for a, _, _ in codes]
```

## For a board: the Sunsoft 5B

Everything famicom-python's mapper 69 needs:

```python
from ay8910_python import PSG, SUNSOFT_5B

sound = PSG(SUNSOFT_5B, record=False)  # record=False: polled, nothing queued

sound.select(value)  # a CPU write to $C000-$DFFF: the register address
sound.write(value)  # a CPU write to $E000-$FFFF: the data
sound.tick()  # once per CPU cycle (run(n) is n of them)
a, b, c = sound.levels()  # the three DAC codes now, 0-31
level = sound.mix()  # the same through SUNSOFT_5B.dac, added: 0.0-3.0
sound.reset()  # the cartridge's power-on
```

- **Time.** One input clock per CPU cycle: the 5B is clocked by the CPU's clock
  (1,789,773 Hz NTSC) and halves it itself, so a tone of period `TP` is
  `1,789,773 / (32·TP)` Hz. A write that lands on CPU cycle `n` is applied after
  `n` ticks since power-on.
- **The address byte.** High bits set in a $C000 write deselect the chip, and the
  $E000 writes after it do nothing, as on the cartridge.
- **No read, no ports.** The cartridge has no way to read the chip.
- **Codes and levels.** `SUNSOFT_5B.dac` is the 5B's logarithmic DAC: 1.5 dB a
  code, codes 0 and 1 silent; a volume `v` is code `2v + 1`.
- **Level against the 2A03.** rainwarrior measured one 5B square at volume 12
  **1.3 dB below** a full-volume 2A03 square at the same pitch, on an AV-modded
  Famicom with a real *Gimmick!* (`db_5b`, NESdev forum thread 17741), and the
  NSFe format's default for the 5B is that figure (-130 millibels). Volume 12 is
  code 25, `SUNSOFT_5B.dac[25]` = 0.354. If the board's square at volume 15 is
  `pulse_out(15)` = 0.149 of its mixer's full scale (the wiki's APU mixer
  formula), the 5B's channels are scaled by
  `0.149 · 10^(-1.3/20) / 0.354` = **0.364**.
- **The amplifier is the board's.** The 5B's output stage is linear up to one
  channel at volume 14 and compresses above (the wiki, "Output"; forum thread
  17745). This core stops at the DAC.

The other machines differ only in the part, the clock and the ports
([docs/contract.md](docs/contract.md)): `chip.port_a_in = read_pins` and
`chip.port_a_out = drive_pins` are the board's callables.

## Install and test

```text
python -m pip install -e ".[dev]"
python -m pytest -q -m "not referee"              # the rules and the kit (seconds)
python scripts/fetch_references.py                # the judges, the data sheets (never committed)
OSS_CAD_SUITE=/path/to/oss-cad-suite sh validation/build_referees.sh
python -m pytest -q                               # plus short referee runs
python scripts/referee.py                         # the synthetic streams, every clock
python scripts/ssg_referee.py                     # the Yamaha parts' waveforms
python scripts/mutation.py                        # the seeded faults
```

Python 3.11 or newer (the newest PyPy supports). No dependencies. The AY's die
model runs under Icarus Verilog (`iverilog`, `vvp`), which the YosysHQ
oss-cad-suite bundle includes; the referee scripts look in `$OSS_CAD_SUITE/bin`
and on the PATH. The board streams are remade with
`scripts/export_board_streams.py` ([docs/validation.md](docs/validation.md)) and
stay local.

**Status** (2026-11-11): rungs 0-4 hold, locally; nothing is pushed or published.
Adoption by famicom-python is next, in that board's own session.

## Licence

MIT. The two judges, lvd and deathsoft's AY-3-8910 model (GPL-3.0) and nukeykt's
YM2203-LLE (GPL-2.0), are fetched into `reference/`, built locally and run as
closed boxes: driven at their pins, their sources not read and nothing of them
copied. They were read when the core was first built; the four behaviours that
reading informed were re-derived from the pins and the documents and rewritten
on 2026-11-14 ([docs/rederived.md](docs/rederived.md),
[docs/provenance.md](docs/provenance.md), [docs/phase0.md](docs/phase0.md),
"Licence").
