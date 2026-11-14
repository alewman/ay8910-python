"""Synthetic event streams for the referee (scripts/referee.py), each exercising one thing.

Times are input clocks. An event is ``(clock, kind, a, b)`` with the kinds of
validation/ay_tb.v. Every stream is a function returning ``(events, clocks)``, so
making one costs nothing until it is run.
"""

from __future__ import annotations

import random
from collections.abc import Callable

WRITE, READ, PINS_A, PINS_B, RESET, SELECT, WRITE_DATA, READ_DATA = range(8)

Event = tuple[int, int, int, int]
Stream = tuple[list[Event], int]


class Writer:
    """Events in time order. ``at`` is the clock the next event lands before."""

    def __init__(self, start: int = 16) -> None:
        self.at = start
        self.events: list[Event] = []

    def write(self, register: int, value: int, wait: int = 0) -> None:
        self.events.append((self.at, WRITE, register, value))
        self.at += wait

    def read(self, register: int, wait: int = 0) -> None:
        self.events.append((self.at, READ, register, 0))
        self.at += wait

    def event(self, kind: int, a: int = 0, b: int = 0, wait: int = 0) -> None:
        self.events.append((self.at, kind, a, b))
        self.at += wait

    def wait(self, clocks: int) -> None:
        self.at += clocks

    def tone(self, channel: int, period: int) -> None:
        self.write(channel * 2, period & 0xFF)
        self.write(channel * 2 + 1, period >> 8)

    def envelope(self, period: int, shape: int | None = None) -> None:
        self.write(11, period & 0xFF)
        self.write(12, period >> 8)
        if shape is not None:
            self.write(13, shape)

    def done(self, tail: int = 4000) -> Stream:
        return self.events, self.at + tail


def silence() -> Stream:
    """Nothing written: the reset state's own output."""
    return Writer().done(20_000)


def tone_periods() -> Stream:
    """Every period from 0 to 40 and a spread up to the top, on all three channels,
    each long enough for several half-cycles; the period changed at every phase of
    the divider."""
    w = Writer()
    w.write(7, 0x38)
    for channel, volume in enumerate((15, 9, 4)):
        w.write(8 + channel, volume)
    for period in (*range(41), 100, 255, 256, 257, 1000, 0xFFF):
        for channel in range(3):
            w.tone(channel, (period + channel) & 0xFFF)
            w.wait(1 + channel)
        w.wait(max(period, 4) * 8 * 5 + period % 8)
    return w.done()


def tone_period_changes() -> Stream:
    """Periods shortened and lengthened under a running counter, seeded: the next
    strobe ends the half-cycle at once when the count is already past."""
    rng = random.Random(1)
    w = Writer()
    w.write(7, 0x38)
    for channel in range(3):
        w.write(8 + channel, rng.randrange(1, 16))
    for _ in range(1500):
        channel = rng.randrange(3)
        if rng.random() < 0.5:
            w.write(channel * 2, rng.randrange(256))
        else:
            w.write(channel * 2 + 1, rng.choice((0, 0, 0, 1, 2, rng.randrange(16))))
        w.wait(rng.choice((1, 3, 8, 17, 64, 200, 777)))
    return w.done()


def noise_periods() -> Stream:
    """Every noise period, each for long enough to hear the register turn over a
    few bits, alone and against a tone."""
    w = Writer()
    w.write(8, 15)
    w.write(9, 11)
    w.tone(1, 9)
    w.write(7, 0x2E)  # A: noise alone; B: tone and noise
    for period in range(32):
        w.write(6, period)
        w.wait(max(period, 1) * 16 * 24 + period)
    return w.done()


def noise_sequence() -> Stream:
    """The whole 131,071-step sequence of the noise register at its fastest."""
    w = Writer()
    w.write(8, 15)
    w.write(7, 0x37)
    w.write(6, 1)
    w.wait(16 * 131_100)
    return w.done()


def noise_period_changes() -> Stream:
    """The noise period rewritten at every phase, seeded."""
    rng = random.Random(2)
    w = Writer()
    w.write(8, 15)
    w.write(7, 0x37)
    for _ in range(1500):
        w.write(6, rng.choice((0, 1, 2, 3, 5, rng.randrange(32))))
        w.wait(rng.choice((1, 2, 5, 16, 33, 150, 400)))
    return w.done()


def envelope_shapes() -> Stream:
    """All sixteen shapes at three periods, each through several ramps."""
    w = Writer()
    w.write(7, 0x3F)
    w.write(8, 0x10)
    w.write(9, 0x1F)
    w.write(10, 0x10)
    for period in (1, 2, 5):
        for shape in range(16):
            w.envelope(period, shape)
            w.wait(period * 16 * 16 * 5 + shape)
    return w.done()


def envelope_periods() -> Stream:
    """Envelope periods 0 to 20 and a spread upward, the shape rewritten at every
    phase of the divider, and the period changed under a running ramp."""
    w = Writer()
    w.write(7, 0x3F)
    w.write(8, 0x10)
    for period in (*range(21), 100, 255, 256, 1000):
        for phase in range(8):
            w.envelope(period, 0x0E if period < 21 else 0x0C)
            w.wait(max(period, 1) * 16 * 20 + 8 + phase)
        w.envelope(max(period // 2, 0))
        w.wait(max(period, 1) * 16 * 9)
    w.envelope(0xFFFF, 0x08)
    w.wait(8 * 0xFFFF * 2 + 5000)
    return w.done()


def envelope_restarts() -> Stream:
    """The shape register rewritten mid-ramp, seeded: shape, period and timing."""
    rng = random.Random(3)
    w = Writer()
    w.write(7, 0x3F)
    for channel in range(3):
        w.write(8 + channel, 0x10)
    for _ in range(1200):
        choice = rng.random()
        if choice < 0.5:
            w.write(13, rng.randrange(16))
        elif choice < 0.8:
            w.write(11, rng.choice((0, 1, 2, 3, rng.randrange(8))))
        else:
            w.write(12, rng.choice((0, 0, 0, 1)))
        w.wait(rng.choice((1, 2, 7, 16, 100, 300, 900)))
    return w.done()


def mixer_and_volume() -> Stream:
    """Every mixer value with tone, noise and envelope all running, then every
    volume value, written at every phase: the gates and the volume act at once."""
    w = Writer()
    w.tone(0, 3)
    w.tone(1, 5)
    w.tone(2, 11)
    w.write(6, 2)
    w.envelope(3, 0x0E)
    for channel, volume in enumerate((15, 0x10, 7)):
        w.write(8 + channel, volume)
    for mixer in range(64):
        w.write(7, mixer)
        w.wait(301)
    w.write(7, 0x00)
    for volume in range(256):
        w.write(8 + volume % 3, volume)
        w.wait(97)
    return w.done()


def registers_read_back() -> Stream:
    """Every register written with $FF, $00 and seeded bytes and read back: each
    register returns only its own width."""
    rng = random.Random(4)
    w = Writer()
    w.write(7, 0xC0)  # both ports outputs, so 14 and 15 read their latches
    for value in (0xFF, 0x00, 0xA5, 0x5A, *(rng.randrange(256) for _ in range(40))):
        for register in range(16):
            data = value if register != 7 else (value | 0xC0)
            w.write(register, data, wait=3)
            w.read(register, wait=5)
    for register in range(16):
        w.read(register, wait=2)
    return w.done()


def address_latch() -> Stream:
    """Address bytes with high bits set deselect the chip: the writes and reads
    after them go nowhere, and the latch keeps its register."""
    rng = random.Random(5)
    w = Writer()
    w.write(7, 0x38)
    w.write(8, 12)
    w.tone(0, 6)
    for _ in range(600):
        choice = rng.random()
        if choice < 0.3:
            w.event(SELECT, rng.choice((0, 1, 8, 8, 7, 0x10, 0x18, 0x80, 0xF8, rng.randrange(256))))
        elif choice < 0.7:
            w.event(WRITE_DATA, 0, rng.choice((0x38, 3, 9, 15, 0, rng.randrange(256))))
        else:
            w.event(READ_DATA)
        w.wait(rng.choice((1, 5, 40, 130)))
    return w.done()


def ports() -> Stream:
    """Both ports as inputs and outputs: the pins driven from outside, the latches
    written in both directions, the direction bits flipped."""
    rng = random.Random(6)
    w = Writer()
    for _ in range(800):
        choice = rng.random()
        if choice < 0.2:
            w.event(PINS_A, rng.randrange(256))
        elif choice < 0.4:
            w.event(PINS_B, rng.randrange(256))
        elif choice < 0.55:
            w.write(7, rng.choice((0x00, 0x40, 0x80, 0xC0)) | rng.randrange(64))
        elif choice < 0.7:
            w.write(14, rng.randrange(256))
        elif choice < 0.85:
            w.write(15, rng.randrange(256))
        else:
            w.read(rng.choice((14, 15, 7)))
        w.wait(rng.choice((1, 3, 20)))
    return w.done()


def resets() -> Stream:
    """/RESET in the middle of everything, at every phase of the divider."""
    rng = random.Random(7)
    w = Writer()
    for burst in range(60):
        w.write(7, rng.randrange(64))
        for channel in range(3):
            w.tone(channel, rng.randrange(1, 12))
            w.write(8 + channel, rng.choice((15, 0x10, rng.randrange(32))))
        w.write(6, rng.randrange(1, 6))
        w.envelope(rng.randrange(1, 5), rng.randrange(16))
        w.wait(900 + burst % 8 + rng.randrange(64))
        w.event(RESET)
        w.wait(rng.randrange(1, 120))
    return w.done()


def random_writes(seed: int, writes: int, values: str = "any") -> Callable[[], Stream]:
    """Seeded writes to every register at seeded times, with reads among them.
    ``values``: "any" byte, or "busy" ones that keep everything audible (short
    periods, envelope volumes, open gates)."""

    def make() -> Stream:
        rng = random.Random(seed)
        w = Writer()
        for _ in range(writes):
            register = rng.randrange(16)
            if rng.random() < 0.08:
                w.read(register)
            elif values == "any":
                w.write(register, rng.randrange(256))
            elif register in (1, 3, 5, 12):
                w.write(register, rng.choice((0, 0, 0, 0, 1)))
            elif register in (0, 2, 4, 6, 11):
                w.write(register, rng.randrange(12))
            elif register == 7:
                w.write(register, rng.randrange(256) & rng.randrange(256))
            else:
                w.write(register, rng.randrange(256))
            w.wait(rng.choice((0, 1, 2, 3, 7, 8, 9, 31, 64, 255, 600, 2500)))
        return w.done()

    return make


def random_events(seed: int, events: int) -> Callable[[], Stream]:
    """Seeded events of every kind at seeded times: writes that keep things
    audible, bare address and data bytes, reads, the ports' pins, and now and
    then /RESET."""

    def make() -> Stream:
        rng = random.Random(seed)
        w = Writer()
        for _ in range(events):
            choice = rng.random()
            register = rng.randrange(16)
            if choice < 0.55:
                if register in (1, 3, 5, 12):
                    value = rng.choice((0, 0, 0, 1, rng.randrange(256)))
                elif register in (0, 2, 4, 6, 11):
                    value = rng.choice((rng.randrange(10), rng.randrange(256)))
                else:
                    value = rng.randrange(256)
                w.write(register, value)
            elif choice < 0.65:
                w.read(register)
            elif choice < 0.73:
                w.event(SELECT, rng.choice((register, register, rng.randrange(256))))
            elif choice < 0.83:
                w.event(WRITE_DATA, 0, rng.randrange(256))
            elif choice < 0.90:
                w.event(READ_DATA)
            elif choice < 0.94:
                w.event(PINS_A, rng.randrange(256))
            elif choice < 0.98:
                w.event(PINS_B, rng.randrange(256))
            else:
                w.event(RESET)
            w.wait(rng.choice((0, 1, 1, 2, 3, 5, 8, 13, 40, 100, 333, 1200)))
        return w.done()

    return make


def long_tones() -> Stream:
    """The longest tone period, and long envelope and noise periods, left to run."""
    w = Writer()
    w.write(7, 0x30)
    w.write(8, 15)
    w.write(9, 0x10)
    w.write(10, 9)
    w.tone(0, 0xFFF)
    w.tone(1, 0x800)
    w.tone(2, 0x3FF)
    w.write(6, 31)
    w.envelope(0x1234, 0x0A)
    w.wait(8 * 0x1234 * 16 * 5)
    return w.done()


STREAMS: dict[str, Callable[[], Stream]] = {
    "silence": silence,
    "tone_periods": tone_periods,
    "tone_period_changes": tone_period_changes,
    "noise_periods": noise_periods,
    "noise_sequence": noise_sequence,
    "noise_period_changes": noise_period_changes,
    "envelope_shapes": envelope_shapes,
    "envelope_periods": envelope_periods,
    "envelope_restarts": envelope_restarts,
    "mixer_and_volume": mixer_and_volume,
    "registers_read_back": registers_read_back,
    "address_latch": address_latch,
    "ports": ports,
    "resets": resets,
    "long_tones": long_tones,
    "random_any_1": random_writes(11, 6000),
    "random_any_2": random_writes(12, 6000),
    "random_busy_1": random_writes(21, 6000, "busy"),
    "random_busy_2": random_writes(22, 6000, "busy"),
    "random_busy_3": random_writes(23, 6000, "busy"),
    "random_events_1": random_events(31, 8000),
    "random_events_2": random_events(32, 8000),
    "random_events_3": random_events(33, 8000),
    "random_events_4": random_events(34, 8000),
}
