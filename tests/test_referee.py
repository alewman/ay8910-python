# SPDX-License-Identifier: MIT
"""The core against the referees, on streams short enough to run with the tests.

The long runs are scripts/referee.py's and scripts/ssg_referee.py's, by hand, and
are recorded in docs/validation.md. These need the referees built
(validation/build_referees.sh) and are skipped without them.
"""

from __future__ import annotations

import shutil

import pytest
import referee
import ssg_referee
from streams import STREAMS

from ay8910_python import AY8910, AY8912, SUNSOFT_5B, YM2149

pytestmark = pytest.mark.referee

HAVE_DIE = referee.REFEREE.exists() and (
    shutil.which("vvp") is not None or shutil.which("vvp", path=referee.suite_path()) is not None
)
needs_die = pytest.mark.skipif(not HAVE_DIE, reason="the die model is not built")
needs_ssg = pytest.mark.skipif(not ssg_referee.REFEREE.exists(), reason="ssg_ref is not built")

SHORT = ["silence", "registers_read_back", "address_latch", "ports", "mixer_and_volume", "resets"]


@needs_die
@pytest.mark.parametrize("name", SHORT)
def test_every_clock_equals_the_ay_3_8910s_die(name: str) -> None:
    stream, clocks = STREAMS[name]()
    assert referee.compare(AY8910, stream, clocks) is None


@needs_die
@pytest.mark.parametrize("variant", [AY8912, YM2149, SUNSOFT_5B], ids=lambda v: v.name)
def test_the_other_parts_as_far_as_the_die_judges_them(variant) -> None:
    stream, clocks = STREAMS["mixer_and_volume"]()
    assert referee.compare(variant, stream, clocks) is None


@needs_die
def test_the_referee_catches_a_wrong_core(monkeypatch: pytest.MonkeyPatch) -> None:
    from ay8910_python import chip

    monkeypatch.setattr(chip, "STROBE_PHASE", 1)
    stream, clocks = STREAMS["mixer_and_volume"]()
    assert referee.compare(AY8910, stream, clocks) is not None


@needs_ssg
def test_the_yamaha_parts_waveforms_equal_the_ym2203s_die() -> None:
    ranks = ssg_referee.die_levels()
    for case in ssg_referee.cases()[::9]:
        for variant in (YM2149, SUNSOFT_5B):
            assert ssg_referee.compare(variant, case, ranks)[1] is None, case.name
