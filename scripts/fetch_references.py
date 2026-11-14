#!/usr/bin/env python
"""Fetch the referees' sources, the detectors and the pinned documents.

    python scripts/fetch_references.py            # fetch what is missing
    python scripts/fetch_references.py --verify   # only check what is there

Into ``reference/`` (ignored). The two judges are GPL (lvd2's AY-3-8910 model
GPL-3.0, Nuked's YM2203-LLE GPL-2.0): read and run as referees here, never copied
into this repository. MAME's ay8910 (BSD-3-Clause), dnotq's ym2149_audio
(BSD-3-Clause) and ayumi (MIT) are read and cited. The documents are checked by
SHA-256; the wiki pages are snapshots of pages that change, so a mismatch there
means the page was edited since, not that the fetch failed, and the forum
threads, which never fetch the same twice, carry no pin at all.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "reference" / "src"

MAME = "518bb5e53379c124833415da5cb2d22d6acf845a"
MAME_RAW = f"https://raw.githubusercontent.com/mamedev/mame/{MAME}/src/devices/sound"

REPOS = [
    {
        "path": "ay-3-8910_reverse_engineered",
        "url": "https://github.com/lvd2/ay-3-8910_reverse_engineered",
        "rev": "cf8d14db0aec5ae86ed4f4e6e67bf14c40a42d77",
        "why": "deathsoft's schematic of the AY-3-8910 from its die and lvd's Verilog "
        "model of it: the AY judge. GPL-3.0.",
    },
    {
        "path": "YM2203-LLE",
        "url": "https://github.com/nukeykt/YM2203-LLE",
        "rev": "817387fd89affd0db5331034d6ae04d919e25a5e",
        "why": "nukeykt's YM2203C from its die; its SSG block is Yamaha's own PSG: "
        "the judge of the Yamaha parts' steps. GPL-2.0.",
    },
    {
        "path": "ym2149_audio",
        "url": "https://github.com/dnotq/ym2149_audio",
        "rev": "ce6654e79768d3aff7f345f1fed51f33a8be593d",
        "why": "Matthew Hagerty's YM2149 in VHDL, written from deathsoft's schematic "
        "and a real YM2149: a detector. BSD-3-Clause.",
    },
    {
        "path": "ayumi",
        "url": "https://github.com/true-grue/ayumi",
        "rev": "07c08b4874c359169e4a028edf73f046d8b763e2",
        "why": "Peter Sovietov's emulator; its DAC tables are measurements of real "
        "chips: read for the levels. MIT.",
    },
    {
        "path": "nes-audio-tests",
        "url": "https://github.com/bbbradsmith/nes-audio-tests",
        "rev": "99ef107f3f3ffe19f72937507ca0820a4f5c34cd",
        "why": "rainwarrior's hardware test ROMs for the Sunsoft 5B (sources and "
        "builds): the programs of the 5B streams. Never committed here.",
    },
]

FILES = [
    {
        "path": "reference/src/mame/ay8910.cpp",
        "url": f"{MAME_RAW}/ay8910.cpp",
        "sha256": "865e8ea6ff17acf107f00c48f39ee04df48319fc1780aa0ddb635d754fa2d514",
        "why": "MAME's AY-3-8910/YM2149 (Couriersud and others): the emulator "
        "detector, and its DAC models. BSD-3-Clause.",
    },
    {
        "path": "reference/src/mame/ay8910.h",
        "url": f"{MAME_RAW}/ay8910.h",
        "sha256": "89eb77b5baf6ae790b970c1aec972be75b55bc292521fcf83e2d6d79647a62d8",
        "why": "Its header: the part list and the per-part flags.",
    },
    {
        "path": "reference/docs/generalinstrument_ay-3-8910.pdf",
        "url": "https://map.grauw.nl/resources/sound/generalinstrument_ay-3-8910.pdf",
        "sha256": "a783dc24e16326852c27d0d216d6f92493596245f9c5bef55913ca7a145ed0f7",
        "why": "General Instrument, AY-3-8910/8912/8913 data sheet: the programmer's "
        "model, the pins, the DAC's normalised voltages.",
    },
    {
        "path": "reference/docs/yamaha_ym2149.pdf",
        "url": "https://map.grauw.nl/resources/sound/yamaha_ym2149.pdf",
        "sha256": "5a6be927846ef56142a17b4223a81b830d0ff75345b2eec7abe4276169dce8cb",
        "why": "Yamaha, YM2149 SSG data sheet: /SEL, the 32-step envelope, the levels.",
    },
    {
        "path": "reference/docs/Sunsoft_5B_audio.wiki",
        "url": "https://www.nesdev.org/w/index.php?title=Sunsoft_5B_audio&action=raw",
        "sha256": "c403df6262076e879fd5b3698b9ca403faf43d3d8bcae66747bc93faac53fd0b",
        "live": True,
        "why": "NESdev wiki: the 5B's sound, with rainwarrior's hardware verifications.",
    },
    {
        "path": "reference/docs/Sunsoft_FME-7.wiki",
        "url": "https://www.nesdev.org/w/index.php?title=Sunsoft_FME-7&action=raw",
        "sha256": "ff423a1860695e95b731e4c1d820d563aa3d579c89fe7f335753daec6d664694",
        "live": True,
        "why": "NESdev wiki: the mapper the 5B extends ($C000 and $E000).",
    },
    {
        "path": "reference/docs/NSFe.wiki",
        "url": "https://www.nesdev.org/w/index.php?title=NSFe&action=raw",
        "sha256": "6e363980c4b7df24a6478b6e6e983f28ecd5fbf34cd76aeed97a4554b01e0a46",
        "live": True,
        "why": "NESdev wiki: the `mixe` chunk's default level for the 5B against the APU.",
    },
    {
        "path": "reference/docs/nesdev-forum-17741.html",
        "url": "https://forums.nesdev.org/viewtopic.php?t=17741",
        "sha256": "",
        "live": True,
        "why": "rainwarrior's audio levels survey: the 5B's measured level (db_5b).",
    },
    {
        "path": "reference/docs/nesdev-forum-17745.html",
        "url": "https://forums.nesdev.org/viewtopic.php?t=17745",
        "sha256": "",
        "live": True,
        "why": "rainwarrior's 5B amplifier investigation: linear to volume 14, then not.",
    },
]

#: Fetched with curl under a generic user agent: some of these hosts answer Python's
#: own with 403 Forbidden.
USER_AGENT = "reference-fetch/1.0"


def sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def fetch_files(verify: bool) -> int:
    bad = 0
    for entry in FILES:
        path = ROOT / entry["path"]
        have = sha256(path)
        if have == entry["sha256"]:
            print(f"{entry['path']}: ok")
            continue
        if have is not None and entry.get("live"):
            # A forum page never fetches the same twice and carries no pin.
            state = "edited upstream since the pin" if entry["sha256"] else "a snapshot, unpinned"
            print(f"{entry['path']}: present, {state} (a live page)")
            continue
        if verify:
            print(f"{entry['path']}: missing or wrong SHA-256")
            bad += 1
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        fetched = subprocess.run(
            ["curl", "-sSfL", "--max-time", "120", "-A", USER_AGENT, entry["url"]],
            capture_output=True,
        )
        if fetched.returncode:
            print(f"{entry['path']}: curl failed: {fetched.stderr.decode().strip()}")
            bad += 1
            continue
        data = fetched.stdout
        got = hashlib.sha256(data).hexdigest()
        if got != entry["sha256"] and not entry.get("live"):
            print(f"{entry['path']}: fetched file has the wrong SHA-256 ({got}); not saved")
            bad += 1
            continue
        path.write_bytes(data)
        note = "" if got == entry["sha256"] else f" (a live page, now {got[:12]})"
        print(f"{entry['path']}: fetched{note}")
    return bad


def head(path: Path) -> str | None:
    if not (path / ".git").exists():
        return None
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True
    )
    return result.stdout.strip() or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--verify", action="store_true", help="check, do not fetch")
    args = parser.parse_args(argv)
    bad = 0
    for entry in REPOS:
        path = SRC / entry["path"]
        if head(path) == entry["rev"]:
            print(f"{entry['path']}: at {entry['rev'][:7]}")
            continue
        if args.verify:
            print(f"{entry['path']}: missing or not at {entry['rev'][:7]}")
            bad += 1
            continue
        path.mkdir(parents=True, exist_ok=True)
        git = ["git", "-C", str(path)]
        if not (path / ".git").exists():
            subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run(
            [*git, "fetch", "-q", "--depth", "1", entry["url"], entry["rev"]], check=True
        )
        subprocess.run([*git, "checkout", "-q", "--detach", "FETCH_HEAD"], check=True)
        if head(path) != entry["rev"]:
            print(f"{entry['path']}: fetched the wrong revision")
            bad += 1
            continue
        print(f"{entry['path']}: fetched {entry['rev'][:7]}")
    bad += fetch_files(args.verify)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
