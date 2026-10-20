#!/usr/bin/env python3
"""Static validation for the multi-version VCN/VDA tables.

Checks the generated kernel call-site tables, the per-build user-space VA/AppleGVA page patches, the
per-build source identity strings, and the build-selection code paths.  This does not execute Apple
code; it is a consistency check for the data imported from the 14.8.9 and 15.8.1 builds.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = 0x1000

KERNEL_DATA = ROOT / "NootedRed" / "VCNKernelData.hpp"
VCN_BRIDGE = ROOT / "NootedRed" / "VCNBridge.cpp"
HEADERS = {
    "Sequoia VA": (ROOT / "NootedRed" / "VDAVAData.hpp", "15.8.1", "24H32", 9, 12),
    "Sonoma VA": (ROOT / "NootedRed" / "VDAVADataSonoma.hpp", "14.8.9", "23J631", 9, 12),
    "Sequoia GVA": (ROOT / "NootedRed" / "VDAGVAData.hpp", "15.8.1", "24H32", 1, 1),
    "Sonoma GVA": (ROOT / "NootedRed" / "VDAGVADataSonoma.hpp", "14.8.9", "23J631", 1, 1),
}


class Failure(RuntimeError):
    pass


def arrays(text: str) -> dict[str, bytes]:
    result = {}
    for match in re.finditer(r"(?:inline constexpr |static const )UInt8\s+(\w+)\s*\[(?:4096)?\]\s*=\s*\{(.*?)\};",
                             text, re.S):
        values = re.findall(r"0x([0-9A-Fa-f]{2})", match.group(2))
        result[match.group(1)] = bytes(int(value, 16) for value in values)
    return result


def parse_call_patches(text: str, name: str) -> list[dict]:
    match = re.search(rf"inline constexpr CallPatch\s+{name}\[\]\s*=\s*\{{(.*?)\n    \}};", text, re.S)
    if not match:
        raise Failure(f"{name} not found in {KERNEL_DATA}")
    entries = []
    for entry in re.finditer(
        r'\{\s*"([^"]+)"\s*,\s*(0x[0-9A-Fa-f]+)\s*,\s*\{\s*([^}]+)\}\s*,\s*(0x[0-9A-Fa-f]+)\s*,?\s*\}',
        match.group(1),
    ):
        symbol, offset, original, new_slot = entry.groups()
        original_bytes = bytes(int(value, 16) for value in re.findall(r"0x([0-9A-Fa-f]{2})", original))
        if len(original_bytes) != 6:
            raise Failure(f"{name}: {symbol} original is {len(original_bytes)} bytes, expected 6")
        entries.append({
            "symbol": symbol,
            "offset": int(offset, 16),
            "original": original_bytes,
            "newSlot": int(new_slot, 16),
        })
    if len(entries) != 20:
        raise Failure(f"{name}: parsed {len(entries)} entries, expected 20")
    return entries


def parse_page_patches(text: str, label: str) -> tuple[int, int, set[str]]:
    page_arrays = arrays(text)
    match = re.search(r"inline constexpr UserPatches::PagePatch\s+Patches\[\]\s*=\s*\{(.*?)\n    \};", text, re.S)
    if not match:
        raise Failure(f"{label}: Patches[] not found")
    entries = []
    for entry in re.finditer(
        r"\{UserPatcher::FileSegment::SegmentTextText,\s*(\w+),\s*(\w+),\s*(\w+),\s*"
        r"sizeof\((\w+)\),\s*(\d+),\s*(\d+)\}",
        match.group(1),
    ):
        page_name, find_name, replace_name, size_name, skip, count = entry.groups()
        if page_name not in page_arrays:
            raise Failure(f"{label}: page array {page_name} missing")
        if find_name not in page_arrays or replace_name not in page_arrays:
            raise Failure(f"{label}: find/replace array missing")
        if size_name != find_name:
            raise Failure(f"{label}: sizeof({size_name}) does not match {find_name}")
        if len(page_arrays[page_name]) != PAGE:
            raise Failure(f"{label}: {page_name} is not a 4 KiB page")
        find, replace = page_arrays[find_name], page_arrays[replace_name]
        if not find or len(find) != len(replace):
            raise Failure(f"{label}: {find_name}/{replace_name} length mismatch")
        page = page_arrays[page_name]
        occurrences = page.count(find)
        if int(skip) + int(count) > occurrences:
            raise Failure(f"{label}: {find_name} has {occurrences} occurrence(s), skip/count out of range")
        entries.append((page_name, find_name, int(skip), int(count)))
    pages = {entry[0] for entry in entries}
    return len(entries), sum(entry[3] for entry in entries), pages


def main() -> int:
    kernel_text = KERNEL_DATA.read_text()
    sequoia = parse_call_patches(kernel_text, "CallPatches")
    sonoma = parse_call_patches(kernel_text, "CallPatches_Sonoma")
    max_match = re.search(r"kMaxCallPatches\s*=\s*(\d+)", kernel_text)
    if max_match is None or int(max_match.group(1)) < len(sequoia):
        raise Failure("kMaxCallPatches is missing or too small")
    if not any(entry["newSlot"] == 0 for entry in sequoia) or not any(entry["newSlot"] == 0 for entry in sonoma):
        raise Failure("expected a signalGPUWorkSubmitted call patch in both kernel tables")
    if sonoma == sequoia:
        raise Failure("Sonoma and Sequoia call-site tables are identical; expected build-specific data")
    selector = re.search(r"getCallPatches\(size_t&[^)]*\)(.*?)\n    \}", kernel_text, re.S)
    if selector is None or "major() == 23" not in selector.group(1):
        raise Failure("getCallPatches() does not select the Darwin 23 (Sonoma) table")
    print(f"kernel tables: Sequoia {len(sequoia)} sites, Sonoma {len(sonoma)} sites, max {max_match.group(1)}")

    bridge_text = VCN_BRIDGE.read_text()
    for token in ('"23J"', '"24H"', "major() == 23", "major() == 24", "CallPatches", "getCallPatches"):
        if token not in bridge_text:
            raise Failure(f"VCNBridge.cpp is missing the multi-version marker {token!r}")
    if "isSupportedBuild" not in bridge_text:
        raise Failure("VCNBridge.cpp has no build gate")
    print("bridge: 14.8.x (23J) / 15.8.x (24H) dispatch present")

    for label, (path, version, build, expected_records, expected_sites) in HEADERS.items():
        if not path.is_file():
            raise Failure(f"{label}: {path} missing")
        text = path.read_text()
        if version not in text or build not in text:
            raise Failure(f"{label}: source identity does not mention {version} / {build}")
        entries = re.findall(
            r"\{UserPatcher::FileSegment::SegmentTextText,\s*(\w+),\s*(\w+),\s*(\w+),\s*"
            r"sizeof\(\w+\)\s*,\s*(\d+)\s*,\s*(\d+)\}",
            text,
        )
        per_page = {}
        pages = {}
        for page_name, _find_name, _replace_name, _skip, count in entries:
            per_page[page_name] = per_page.get(page_name, 0) + int(count)
            pages[page_name] = True
        for page_name, sites_on_page in per_page.items():
            if sites_on_page > 16:
                raise Failure(f"{label}: {page_name} has {sites_on_page} sites, backend cap is 16")
        records, sites, pages = parse_page_patches(text, label)
        if records != expected_records or sites != expected_sites:
            raise Failure(
                f"{label}: {records} record(s), {sites} site(s); expected {expected_records}/{expected_sites}"
            )
        if len(pages) > 16:
            raise Failure(f"{label}: {len(pages)} distinct pages exceeds the native backend cap")
        print(f"{label}: {records} record(s), {sites} site(s), {len(pages)} page(s)")

    print("all multi-version VCN/VDA data checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Failure as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
