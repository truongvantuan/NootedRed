#!/usr/bin/env python3
"""Host-side check of the version/family patch-set selection rules.

Reads the actual C++ patch-set table so the family ordering and OS ranges cannot drift from the kext.
It does not load the kext or exercise the runtime major-version/semantic fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

RENOIR = 1 << 3
RENOIR_E = 1 << 4
GREEN_SARDINE = 1 << 5
RAVEN = 1 << 0
RAVEN2 = 1 << 1
PICASSO = 1 << 2
ALL = 0x3F


@dataclass(frozen=True)
class PatchSet:
    name: str
    minimum: tuple[int, int]
    maximum: tuple[int, int]
    apus: int


def load_sets() -> list[PatchSet]:
    source = (Path(__file__).resolve().parents[1] / "NootedRed/UserPatches.cpp").read_text()
    table = source.split("kGLDriverPatchSets[] = {", 1)[1].split("\n    };", 1)[0]
    pattern = re.compile(
        r'\{"([^"]+)",\s*PenguinWizardry::KernelVersion\((\d+),\s*(\d+)\),\s*'
        r'PenguinWizardry::KernelVersion\((\d+),\s*(\d+)\),\s*(.*?),\s*k\w+\s*,', re.S
    )
    masks = {"Raven": RAVEN, "Raven2": RAVEN2, "Picasso": PICASSO, "Renoir": RENOIR,
             "RenoirE": RENOIR_E, "GreenSardine": GREEN_SARDINE, "All": ALL}
    result = []
    for name, low_major, low_minor, high_major, high_minor, expression in pattern.findall(table):
        apus = 0
        names = re.findall(r'UserPatches::kApu(\w+)', expression)
        if not names:
            raise ValueError(f"no APU mask parsed for {name}")
        for mask in names:
            apus |= masks[mask]
        result.append(PatchSet(name, (int(low_major), int(low_minor)),
                               (int(high_major), int(high_minor)), apus))
    if not result:
        raise ValueError("no patch sets parsed")
    return result


SETS = load_sets()


def select(major: int, minor: int, apus: int) -> str | None:
    for patch_set in SETS:
        if (major, minor) < patch_set.minimum:
            continue
        if (major, minor) > patch_set.maximum:
            continue
        if apus == 0:
            if patch_set.apus != ALL:
                continue
        elif patch_set.apus & apus == 0:
            continue
        return patch_set.name
    return None


def main() -> None:
    cases = [
        (24, 6, RENOIR | GREEN_SARDINE, "15.x / Renoir-family"),
        (24, 6, RENOIR_E, "15.x / Renoir-family"),
        (24, 6, RAVEN, "15.x / Raven-family"),
        (24, 6, RAVEN2, "15.x / Raven-family"),
        (24, 6, PICASSO, "15.x / Raven-family"),
        (24, 6, 0, "15.x / gfx9 APU fallback"),
        (24, 5, RENOIR, "15.x / Renoir-family"),
        (24, 7, RENOIR, "15.x / Renoir-family"),
        (25, 6, RENOIR, "26.x / Tahoe gfx9 APU"),
        (25, 5, RENOIR, "26.x / Tahoe gfx9 APU"),
        (23, 0, RENOIR, "14.x / Sonoma gfx9 APU"),
        (23, 6, RENOIR, "14.x / Sonoma gfx9 APU"),
        (23, 6, RAVEN, "14.x / Sonoma gfx9 APU"),
        (23, 6, 0, "14.x / Sonoma gfx9 APU"),
        (23, 99, PICASSO, "14.x / Sonoma gfx9 APU"),
        (23, 100, RENOIR, None),
        (22, 6, RENOIR, None),
    ]
    for major, minor, apus, expected in cases:
        got = select(major, minor, apus)
        status = "ok" if got == expected else "FAIL"
        print(f"{status}: macOS/Darwin {major}.{minor} apus=0x{apus:02X} -> {got}")
        if got != expected:
            raise SystemExit(1)
    print("all patch-set selection cases passed")


if __name__ == "__main__":
    main()
