# SPDX-License-Identifier: MIT
"""ay8910-python: a readable, pure-Python AY-3-8910 / YM2149 / Sunsoft 5B reference core.

The chip is :class:`PSG`; the parts are :data:`AY8910`, :data:`AY8912`,
:data:`AY8913`, :data:`YM2149` and :data:`SUNSOFT_5B`. The contract -- the bus, the
time unit, the outputs -- is docs/contract.md.
"""

from .chip import CLOCKS_PER_STEP, COUNT_PHASE, PSG, STROBE_PHASE
from .variants import (
    AY8910,
    AY8912,
    AY8913,
    DAC_5B,
    DAC_AY_LOGARITHMIC,
    DAC_AY_MEASURED,
    DAC_YM_DATASHEET,
    DAC_YM_MEASURED,
    SUNSOFT_5B,
    VARIANTS,
    YM2149,
    PSGVariant,
)

__all__ = [
    "AY8910",
    "AY8912",
    "AY8913",
    "CLOCKS_PER_STEP",
    "COUNT_PHASE",
    "DAC_5B",
    "DAC_AY_LOGARITHMIC",
    "DAC_AY_MEASURED",
    "DAC_YM_DATASHEET",
    "DAC_YM_MEASURED",
    "PSG",
    "STROBE_PHASE",
    "SUNSOFT_5B",
    "VARIANTS",
    "YM2149",
    "PSGVariant",
]
__version__ = "0.1.0.dev0"
