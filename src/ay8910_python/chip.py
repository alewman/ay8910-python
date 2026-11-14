# SPDX-License-Identifier: MIT
"""The AY-3-8910 programmable sound generator and its Yamaha relatives, clock by clock.

Three square-wave tone channels, one noise generator, one envelope generator, a
mixer, two 8-bit I/O ports and sixteen registers behind an address latch. The
programmer's model is GI's data sheet and Yamaha's catalog. The timing inside the
divider's eight is what the pins of lvd's model of deathsoft's AY-3-8910 die
schematic show, run as a closed box (``ay_ref``; its source is GPL-3.0 and is not
read): the probes and their answers are docs/rederived.md, and at every input
clock of the referee's streams the three channels drive what that model drives
(docs/validation.md). What the Yamaha parts do differently is data on
:class:`~ay8910_python.variants.PSGVariant`.

The machine (docs/rederived.md, items 1 and 2):

* **One turn of eight internal clocks, two moments in it.** Every counter is an
  up-counter. On the strobe (``STROBE_PHASE``) each counter that may be compared
  is, and one that has reached its period (count >= period) expires: it is
  cleared and *held*. On the count (``COUNT_PHASE``, the next clock) every counter
  counts by one and every hold is let go.
* **A held counter is not compared.** So a counter that has just expired, or come
  out of /RESET, cannot expire at the next strobe: period 0 is period 1, for the
  tones, the noise and the envelope (also the wiki's "Period 0 verification").
* **The strobe stays open for one more clock.** A period written after the
  strobe's clock and before the count's is compared at once, with the count the
  strobe saw. Written at any other time it waits for the next strobe. A period
  shortened under a running count therefore ends the half-cycle early, never
  wraps round (the wiki's "Phase counting verification").
* **The envelope's restart depends on the half of the eight.** A shape write
  before the count clears the envelope's counter and holds it; after the count it
  keeps the counter's lowest bit, clears the rest, and does not hold it. This is
  the model's behaviour measured at its pins, with no hardware statement behind
  it (docs/claims.md).
* **The noise and the envelope run at half their counter's rate.** A flip-flop
  after each counter lets the shift register step, and the AY's 16-step envelope
  move, on every second expiry. Yamaha's 32-step envelope moves on every one.
* **The noise is a 17-bit register shifting left**, fed bit 16 XOR bit 13, or a 1
  while it is all zero, which is how it leaves /RESET; a channel hears the
  *inverse* of bit 16. The taps are the wiki's "LFSR verification" (hardware) and
  MAME's ay8910.cpp, "verified on AY-3-8910 and YM2149 chips" (BSD-3-Clause, the
  same pair mirrored); the start and the polarity are seen at the model's pins
  (the streams ``noise_sequence`` and ``resets``).
"""

from __future__ import annotations

from collections.abc import Callable

from .variants import AY8910, PSGVariant

#: Internal clocks per count: the chip's divide-by-eight.
CLOCKS_PER_STEP = 8
#: Where in the eight the strobe compares the counters and where they count, as
#: clocks after /RESET is released.
STROBE_PHASE = 2
COUNT_PHASE = 3

#: Register numbers, by GI's names (the data sheet counts them in octal, R0-R17).
TONE_A_FINE, TONE_A_COARSE = 0, 1
NOISE_PERIOD, MIXER = 6, 7
VOLUME_A = 8
ENVELOPE_FINE, ENVELOPE_COARSE, ENVELOPE_SHAPE = 11, 12, 13
PORT_A, PORT_B = 14, 15

#: The shape register's bits.
HOLD, ALTERNATE, ATTACK, CONTINUE = 1, 2, 4, 8

Levels = tuple[int, int, int]


class PSG:
    """One chip: its pins, its sixteen registers and its five counters.

    ``registers`` holds what each register keeps of the last byte written: its
    own width on an AY, all eight bits on a Yamaha part (the engine uses only the
    bits a register has a use for). :meth:`levels` is the chip's digital output,
    the DAC code each channel drives this instant, and is what the referee is
    compared on.

    The I/O ports are pins, so they are callables the board supplies:
    ``port_a_in()`` returns the levels the outside drives onto port A's pins
    (unset: the chip's own pull-ups, $FF) and ``port_a_out(value)`` is called with
    the levels the chip drives whenever they change (a port set to input drives
    nothing and its pull-ups read $FF). The same for port B.
    """

    def __init__(self, variant: PSGVariant = AY8910, *, record: bool = True) -> None:
        self.variant = variant
        #: Queue one :meth:`levels` per input clock for :meth:`take_outputs`. A board
        #: that asks for :meth:`levels` itself after each :meth:`tick` passes False.
        self.record = record
        self.port_a_in: Callable[[], int] | None = None
        self.port_b_in: Callable[[], int] | None = None
        self.port_a_out: Callable[[int], None] | None = None
        self.port_b_out: Callable[[int], None] | None = None
        self._envelope_top = variant.envelope_steps - 1
        #: What the chip last drove on ports A and B ($FF: an input, pulled up).
        self._driven = [0xFF, 0xFF]
        self.reset()

    def reset(self) -> None:
        """/RESET, as at power-on: every register 0, every counter 0, the divider at
        the start of its eight, the tones high and the noise register empty.

        Register 7 at 0 enables every tone and both noise and tone on each channel
        and makes both ports inputs; the volumes at 0 keep the channels silent.
        A real part powers on in no particular state; boards pulse /RESET.
        """
        self.registers = [0] * 16
        #: The address latch, and whether the last address byte selected the chip.
        self.address = 0
        self.selected = False
        #: The chip's internal data bus, which keeps its last byte as charge.
        self.bus = 0
        #: The /SEL pin's effect: input clocks per internal clock (1 or 2).
        self.clock_divider = self.variant.clock_divider
        self._divider_count = 0
        self.phase = 0

        #: Each counter has a flip-flop that an expiry sets and the count clears, and
        #: that holds the counter at 0 in between: ``*_held``.
        self.tone_period = [0, 0, 0]
        self.tone_count = [0, 0, 0]
        self.tone_held = [True, True, True]
        self.tone_output = [1, 1, 1]

        self.noise_period = 0
        self.noise_count = 0
        self.noise_held = True
        self.noise_half = 0
        self.noise_register = 0

        self.envelope_period = 0
        self.envelope_count = 0
        self.envelope_held = True
        self.envelope_half = 0
        self.envelope_step = 0
        self.envelope_rising = False
        self.envelope_holding = False
        self.envelope_level = self._envelope_top

        self.clock = 0
        self.outputs: list[Levels] = []
        self._levels = self._mix_levels()
        self._drive_port(PORT_A)
        self._drive_port(PORT_B)

    # -- the bus -----------------------------------------------------------------------

    def select(self, value: int) -> None:
        """Latch an address byte (BDIR and BC1 high).

        The low four bits name the register. The high four must be 0, the chip's
        mask-programmed address with A8 high and /A9 low: any other byte leaves the
        latch alone and deselects the chip, so the data writes and reads that
        follow do nothing (GI's data sheet, "Register Array"; the 5B's $C000 the
        same, Sunsoft_5B_audio.wiki). The address byte leaves 0 on the internal
        bus where an unused register bit would read it (docs/rederived.md, item 3).
        """
        self.selected = (value & 0xF0) == 0
        if self.selected:
            self.address = value & 0x0F
        self.bus = 0

    def write(self, value: int) -> None:
        """Write a data byte to the selected register (BDIR high, BC1 low).

        The registers are latches open for as long as the strobe lasts and the chip
        has no clock of its own for them: the write is taken as an instant, between
        two input clocks. Bring the chip to the moment with :meth:`run` first.
        """
        if self.selected:
            self.bus = value & 0xFF
            self._write_register(self.address, self.bus)

    def read(self) -> int:
        """Read the selected register (BDIR low, BC1 high): what the chip drives
        onto the data pins. A register's own bits are what it keeps; the bits it
        lacks are whatever the internal bus last carried (:meth:`read_register`).

        A deselected chip does not drive the data pins; this returns $FF for it,
        and a board with its own open bus checks ``selected``.
        """
        if not self.selected:
            return 0xFF
        return self.read_register(self.address)

    def write_register(self, register: int, value: int) -> None:
        """An address byte and a data byte together: :meth:`select`, :meth:`write`."""
        self.select(register)
        self.write(value)

    def read_register(self, register: int) -> int:
        """What a read of ``register`` (0-15) returns now, with the latch left as
        it is.

        Registers 14 and 15 are their ports' pins. Any other register gives the
        bits it keeps, and in the bits it lacks the internal bus: the last data
        byte written, or 0 if an address byte came after it. That is the die
        model's answer at its pins (docs/rederived.md, item 3); the usual
        sequence, an address byte then the read, gives the 0 MAME's ay8910.cpp
        reports from a real AY-3-8910 ("inaccessible bits ... read back as 0").
        """
        register &= 0x0F
        if register == PORT_A:
            return self._port_pins(PORT_A, self.port_a_in)
        if register == PORT_B:
            return self._port_pins(PORT_B, self.port_b_in)
        kept = self.variant.register_masks[register]
        return self.registers[register] | (self.bus & ~kept & 0xFF)

    def _write_register(self, register: int, value: int) -> None:
        registers = self.registers
        registers[register] = value & self.variant.register_masks[register]
        if register < NOISE_PERIOD:
            channel = register >> 1
            fine, coarse = registers[channel * 2], registers[channel * 2 + 1]
            self.tone_period[channel] = (coarse & 0x0F) << 8 | fine
        elif register == NOISE_PERIOD:
            self.noise_period = registers[NOISE_PERIOD] & 0x1F
        elif register == MIXER:
            self._drive_port(PORT_A)
            self._drive_port(PORT_B)
        elif register in (ENVELOPE_FINE, ENVELOPE_COARSE):
            self.envelope_period = registers[ENVELOPE_COARSE] << 8 | registers[ENVELOPE_FINE]
        elif register == ENVELOPE_SHAPE:
            self._restart_envelope()
        elif register >= PORT_A:
            self._drive_port(register)
        if self._strobe_open() and register in _PERIOD_REGISTERS:
            # Written after the strobe's clock, before the count's: compared now.
            self._compare()
        self._levels = self._mix_levels()

    # -- the ports ---------------------------------------------------------------------

    def _port_is_output(self, register: int) -> bool:
        """Register 7's bit 6 makes port A an output, bit 7 port B."""
        return bool(self.registers[MIXER] & (0x40 if register == PORT_A else 0x80))

    def _port_bonded(self, register: int) -> bool:
        return ("A" if register == PORT_A else "B") in self.variant.ports

    def _port_pins(self, register: int, outside: Callable[[], int] | None) -> int:
        """The levels on a port's eight pins, which is what a read returns in
        either direction (docs/rederived.md, item 4).

        The outside's levels, or the pull-ups' $FF with nothing driving them (GI:
        "when in the 'input' mode, all pins will read normally high"). As an
        output the chip drives its latch, and a pin the outside pulls low reads
        low (phase0.md, decision 8). A port the part does not bond out has no
        outside: its pull-ups, or its latch."""
        levels = 0xFF
        if outside is not None and self._port_bonded(register):
            levels = outside() & 0xFF
        if self._port_is_output(register):
            levels &= self.registers[register]
        return levels

    def _drive_port(self, register: int) -> None:
        """Tell the board what the chip now drives on a port, if that has changed."""
        port = register - PORT_A
        value = self.registers[register] if self._port_is_output(register) else 0xFF
        if value != self._driven[port]:
            self._driven[port] = value
            out = self.port_a_out if register == PORT_A else self.port_b_out
            if out is not None and self._port_bonded(register):
                out(value)

    # -- time --------------------------------------------------------------------------

    def tick(self) -> None:
        """One input clock. With ``clock_divider`` 2 the chip moves on every second
        one (the second, the fourth, ... after /RESET)."""
        self.clock += 1
        self._divider_count += 1
        if self._divider_count >= self.clock_divider:
            self._divider_count = 0
            phase = self.phase
            self.phase = (phase + 1) & 7
            if phase == STROBE_PHASE:
                self._compare()
                self._levels = self._mix_levels()
            elif phase == COUNT_PHASE:
                self._count()
        if self.record:
            self.outputs.append(self._levels)

    def run(self, clocks: int) -> None:
        """``clocks`` input clocks: :meth:`tick` that many times."""
        tick = self.tick
        for _ in range(clocks):
            tick()

    def _strobe_open(self) -> bool:
        """Whether the clock just run was the strobe's, so that the next is the
        count's and the comparators still see a period written now."""
        return self.phase == (STROBE_PHASE + 1) & 7

    def _compare(self) -> None:
        """The strobe: every counter not held that has reached its period expires."""
        periods, counts, held = self.tone_period, self.tone_count, self.tone_held
        for channel in (0, 1, 2):
            if not held[channel] and counts[channel] >= periods[channel]:
                counts[channel] = 0
                held[channel] = True
                self.tone_output[channel] ^= 1
        if not self.noise_held and self.noise_count >= self.noise_period:
            self.noise_count = 0
            self.noise_held = True
            self.noise_half ^= 1
            if not self.noise_half:
                self._shift_noise()
        if not self.envelope_held and self.envelope_count >= self.envelope_period:
            self.envelope_count = 0
            self.envelope_held = True
            if self._envelope_top == 15:
                self.envelope_half ^= 1
                if self.envelope_half:
                    return
            self._step_envelope()

    def _count(self) -> None:
        """The count: every counter goes up by one and every hold is let go."""
        counts, held = self.tone_count, self.tone_held
        for channel in (0, 1, 2):
            counts[channel] += 1
            held[channel] = False
        self.noise_count += 1
        self.noise_held = False
        self.envelope_count += 1
        self.envelope_held = False

    def _shift_noise(self) -> None:
        """One step of the 17-bit register: left, taking in bit 16 XOR bit 13, or a
        1 while the register is all zero (as /RESET leaves it)."""
        noise = self.noise_register
        feedback = ((noise >> 16) ^ (noise >> 13)) & 1
        self.noise_register = ((noise << 1) | feedback | (noise == 0)) & 0x1FFFF

    # -- the envelope ------------------------------------------------------------------

    def _restart_envelope(self) -> None:
        """A write to the shape register, whatever its value: the envelope starts
        its first ramp again, rising with ATTACK, and anything holding it is let go
        (the wiki's "Envelope phase reset verification").

        Its period counter (docs/rederived.md, item 2): written before this turn's
        count, the counter is cleared and held until the count; written after it,
        only the counter's lowest bit is kept and nothing holds it, so the first
        step comes a count sooner when that bit was 1."""
        if self._counters_counted():
            self.envelope_count &= 1
            self.envelope_held = False
        else:
            self.envelope_count = 0
            self.envelope_held = True
        self.envelope_half = 0
        self.envelope_step = 0
        self.envelope_holding = False
        self.envelope_rising = bool(self.registers[ENVELOPE_SHAPE] & ATTACK)
        self._ramp()

    def _counters_counted(self) -> bool:
        """Whether the divider is in the second half of its eight, the four clocks
        after the count."""
        return self.phase > COUNT_PHASE

    def _ramp(self) -> None:
        top = self._envelope_top
        step = self.envelope_step
        self.envelope_level = step if self.envelope_rising else top - step

    def _step_envelope(self) -> None:
        """One step along the ramp. At the end of a ramp the shape decides: without
        CONTINUE the level is 0 from then on; with HOLD it stays where the ramp
        ended, or at the other end with ALTERNATE as well; otherwise the ramp
        repeats, turned round each time with ALTERNATE."""
        if self.envelope_holding:
            return
        self.envelope_step += 1
        if self.envelope_step <= self._envelope_top:
            self._ramp()
            return
        self.envelope_step = 0
        shape = self.registers[ENVELOPE_SHAPE]
        if not shape & CONTINUE:
            self.envelope_holding = True
            self.envelope_level = 0
        elif shape & HOLD:
            self.envelope_holding = True
            ends_high = self.envelope_rising ^ bool(shape & ALTERNATE)
            self.envelope_level = self._envelope_top if ends_high else 0
        else:
            if shape & ALTERNATE:
                self.envelope_rising = not self.envelope_rising
            self._ramp()

    # -- the outputs -------------------------------------------------------------------

    def _mix_levels(self) -> Levels:
        """The DAC code of each channel: its volume, or the envelope's level, while
        (tone OR tone-disabled) AND (noise OR noise-disabled); 0 otherwise.

        The AY's codes are the 4-bit volume itself. Yamaha's are the 5-bit
        envelope, and a 4-bit volume ``v`` drives ``2v + 1``."""
        registers = self.registers
        mixer = registers[MIXER]
        noise = (~self.noise_register >> 16) & 1
        wide = self.variant.envelope_steps == 32
        codes = []
        for channel in range(3):
            tone_gate = self.tone_output[channel] | (mixer >> channel)
            noise_gate = noise | (mixer >> (channel + 3))
            if not tone_gate & noise_gate & 1:
                codes.append(0)
                continue
            volume = registers[VOLUME_A + channel]
            if volume & 0x10:
                codes.append(self.envelope_level)
            else:
                codes.append((volume & 0x0F) * 2 + 1 if wide else volume & 0x0F)
        return (codes[0], codes[1], codes[2])

    def levels(self) -> Levels:
        """What channels A, B and C drive now: DAC codes, 0-15 on an AY part and
        0-31 on a Yamaha one (``variant.dac`` turns a code into a level)."""
        return self._levels

    def mix(self) -> float:
        """The three channels' levels added, 0.0-3.0, by the variant's DAC table:
        what three output pins tied together through equal resistors would carry.
        The pins' shared load, the filters and the amplifier are the board's."""
        dac = self.variant.dac
        a, b, c = self._levels
        return dac[a] + dac[b] + dac[c]

    def take_outputs(self) -> list[Levels]:
        """Return and clear the queued outputs: one :meth:`levels` per input clock
        run, each the state after that clock."""
        outputs, self.outputs = self.outputs, []
        return outputs

    def take_samples(self) -> list[float]:
        """Return and clear the queued outputs as mixed levels, one :meth:`mix` per
        input clock."""
        dac = self.variant.dac
        return [dac[a] + dac[b] + dac[c] for a, b, c in self.take_outputs()]


#: The registers that hold a counter's period: the tones', the noise's, the envelope's.
_PERIOD_REGISTERS = frozenset((0, 1, 2, 3, 4, 5, NOISE_PERIOD, ENVELOPE_FINE, ENVELOPE_COARSE))
