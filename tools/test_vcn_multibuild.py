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
import os
import shlex
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = 0x1000

KERNEL_DATA_24H32 = ROOT / "NootedRed" / "VCNData" / "24H32.hpp"
KERNEL_DATA_23J631 = ROOT / "NootedRed" / "VCNData" / "23J631.hpp"
VCN_DATA = ROOT / "NootedRed" / "VCNData.hpp"
VCN_SELECTOR = ROOT / "NootedRed" / "VCNData.cpp"
VCN_BRIDGE = ROOT / "NootedRed" / "VCNBridge.cpp"
HEADERS = {
    "Sequoia VA": (ROOT / "NootedRed" / "VDAVAData.hpp", "15.8.1", "24H32", 9, 12),
    "Sonoma VA": (ROOT / "NootedRed" / "VDAVADataSonoma.hpp", "14.8.9", "23J631", 9, 12),
    "Sequoia GVA": (ROOT / "NootedRed" / "VDAGVAData.hpp", "15.8.1", "24H32", 1, 1),
    "Sonoma GVA": (ROOT / "NootedRed" / "VDAGVADataSonoma.hpp", "14.8.9", "23J631", 1, 1),
}


class Failure(RuntimeError):
    pass


def header_text(path: pathlib.Path, seen: set[pathlib.Path] | None = None) -> str:
    """Follow the combined fork's generated-data wrappers and inline page includes."""
    seen = set() if seen is None else seen
    if path in seen:
        return ""
    seen.add(path)
    text = path.read_text()
    for name in re.findall(r'#include\s*[<"]([^>"\n]+)[>"]', text):
        target = path.parent / name
        if target.is_file() and target.suffix in (".hpp", ".inc") and target.name.startswith(("VDAVA", "VDAGVA")):
            text += "\n" + header_text(target, seen)
    return text


def check_compiled_selector() -> None:
    """Run the production selector and compile the actual per-build tables without a kernel."""
    program = r'''
#include <cstddef>
#include <VCNData.hpp>
#include <cassert>
#include <cstring>
int main() {
    struct Case { const char* build; unsigned major, id; bool prefix; };
    for (const auto c : {
        Case{"23J631", 23, 1, false}, Case{"24H32", 24, 2, false}, Case{"25G241", 25, 3, false},
        Case{"23H123", 23, 4, true}, Case{"23G123", 23, 5, true}, Case{"23J632", 23, 6, true},
        Case{"24H33", 24, 7, true}, Case{"25G242", 25, 8, true}, Case{"24G100", 24, 9, true}}) {
        const auto* v = VCNData::findVariant(c.build, c.major, 6);
        assert(v && v->id == c.id && v->buildPrefix == c.prefix);
        assert(v->callPatchCount == 20 && v->guard5000Count == 6 && v->guard6000Count == 6);
        if (c.prefix) assert(!v->hasKernelIdentity && !*v->kernelCollectionUUID);
        assert(VCNData::variantForDarwin(c.major, 6));
        assert(VCNData::hasVariantForDarwin(c.major, 6));
        assert(!VCNData::findVariant(nullptr, c.major, 6));
        assert(!VCNData::findVariant("", c.major, 6));
        assert(!VCNData::findVariant(c.build, c.major, 5));
        assert(!VCNData::findVariant(c.build, c.major, 7));
        assert(!VCNData::findVariant(c.build, c.major == 23 ? 24 : 23, 6));
    }
    assert(VCNData::findVariant("22G513",22,6)->id==10);
    assert(!VCNData::findVariant("22G514",22,6));
    assert(!VCNData::findVariant("22H730",22,6));
    assert(!VCNData::findVariant("24F100", 24, 6));
    assert(!VCNData::findVariant("23K100", 23, 6));
    assert(!VCNData::findVariant("25H100", 25, 6));
    assert(!VCNData::findVariant("24", 24, 6));
    assert(!VCNData::variantForDarwin(26, 6));
}
'''
    with tempfile.TemporaryDirectory(prefix="nred-vcn-") as directory:
        path = pathlib.Path(directory)
        (path / "IOKit").mkdir()
        (path / "IOKit/IOTypes.h").write_text(
            "#pragma once\n#include <cstdint>\n#include <stddef.h>\nusing UInt8=uint8_t; using UInt32=uint32_t;\n")
        source = path / "test.cpp"
        source.write_text("#include <initializer_list>\n" + program)
        compiler = shlex.split(os.environ.get("CXX", "c++"))
        subprocess.run(compiler + ["-std=c++17", "-I" + str(path), "-I" + str(ROOT / "NootedRed"),
                                  str(VCN_SELECTOR), str(source), "-o", str(path / "test")], check=True)
        subprocess.run([str(path / "test")], check=True)
    print("production VCN selector: exact builds take priority; declared families accepted; unrelated builds/Darwin rejected")


def arrays(text: str) -> dict[str, bytes]:
    result = {}
    for match in re.finditer(r"(?:inline constexpr |static const )UInt8\s+(\w+)\s*\[(?:4096)?\]\s*=\s*\{(.*?)\};",
                             text, re.S):
        values = re.findall(r"0x([0-9A-Fa-f]{2})", match.group(2))
        result[match.group(1)] = bytes(int(value, 16) for value in values)
    return result


def parse_call_patches(text: str, label: str, name: str = "CallPatches") -> list[dict]:
    match = re.search(rf"inline constexpr CallPatch\s+{name}\[\]\s*=\s*\{{(.*?)\n    \}};", text, re.S)
    if not match:
        raise Failure(f"{label}: {name} not found")
    entries = []
    for entry in re.finditer(
        r'\{\s*"([^"]+)"\s*,\s*(0x[0-9A-Fa-f]+)\s*,\s*\{\s*([^}]+)\}\s*,\s*(0x[0-9A-Fa-f]+)\s*,?\s*\}',
        match.group(1),
    ):
        symbol, offset, original, new_slot = entry.groups()
        original_bytes = bytes(int(value, 16) for value in re.findall(r"0x([0-9A-Fa-f]{2})", original))
        if len(original_bytes) != 6:
            raise Failure(f"{label}: {symbol} original is {len(original_bytes)} bytes, expected 6")
        entries.append({
            "symbol": symbol,
            "offset": int(offset, 16),
            "original": original_bytes,
            "newSlot": int(new_slot, 16),
        })
    if len(entries) != 20:
        raise Failure(f"{label}: parsed {len(entries)} entries, expected 20")
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
    tables = [("22G513", ROOT / "NootedRed/VCNData/22G513.hpp"), ("24H32", KERNEL_DATA_24H32), ("23J631", KERNEL_DATA_23J631),
              ("25G241", ROOT / "NootedRed/VCNData/25G241.hpp")]
    parsed = []
    for build, path in tables:
        text = path.read_text()
        patches = parse_call_patches(text, build + " CallPatches")
        if len(patches) != 20 or f'Build[] = "{build}"' not in text:
            raise Failure(f"{build}: expected 20 call sites and exact build identifier")
        if 'static_assert(kCallPatchCount <= kMaxCallPatches' not in text:
            raise Failure(f"{build}: missing compile-time bound")
        parsed.append(patches)
        print(f"kernel table {build}: {len(patches)} sites")
    if parsed[0] == parsed[1] or parsed[0] == parsed[2]:
        raise Failure("expected OS-specific call sites")

    data_text = VCN_DATA.read_text()
    selector_text = VCN_SELECTOR.read_text()
    for token in ("findVariant", "variantForDarwin", "hasVariantForDarwin", "kMaxCallPatches"):
        if token not in data_text:
            raise Failure(f"VCNData.hpp is missing {token!r}")
    for token in ("Build22G513::kData", "Build23J631::kData", "Build24H32::kData", "Build25G241::kData",
                  "Build23H::kData", "Build23G::kData", "Build23J::kData", "Build24H::kData",
                  "Build24G::kData", "Build25G::kData", "buildPrefix", "buildMatches", "osversion[i] == '\\0'"):
        if token not in selector_text:
            raise Failure(f"VCNData.cpp is missing {token!r}")
    if 'major() == 23' in selector_text or '"23J"' in selector_text or '"24H"' in selector_text:
        raise Failure("VCNData.cpp still contains a Darwin-major/family-prefix selector")

    bridge_text = VCN_BRIDGE.read_text()
    for token in ("VCNData::variantForDarwin", "VCNData::findVariant", "currentVariant", "hasVariantForDarwin"):
        if token not in bridge_text:
            raise Failure(f"VCNBridge.cpp is missing the exact-build marker {token!r}")
    if "VCNKernelData" in bridge_text or "getCallPatches" in bridge_text:
        raise Failure("VCNBridge.cpp still uses the old VCNKernelData selector")
    print("bridge: exact-build VCNData lookup present")

    page_cases = {
        "Ventura VA": (ROOT / "NootedRed/VDAVADataVentura.hpp", "13.6.4", 8, 11),
        "Ventura GVA": (ROOT / "NootedRed/VDAGVADataVentura.hpp", "13.6.4", 1, 1),
        "Sequoia VA": (ROOT / "NootedRed" / "VDAVAData.hpp", "15.8.1", 9, 12),
        "Sonoma VA": (ROOT / "NootedRed" / "VDAVADataSonoma.hpp", "14.8.9", 9, 12),
        "Sequoia GVA": (ROOT / "NootedRed" / "VDAGVAData.hpp", "15.8.1", 1, 1),
        "Sonoma GVA": (ROOT / "NootedRed" / "VDAGVADataSonoma.hpp", "14.8.9", 1, 1),
    }
    page_cases.update({
        "Tahoe VA": (ROOT / "NootedRed/VDAVADataTahoe.hpp", "26.7.1", 10, 12),
        "Tahoe GVA": (ROOT / "NootedRed/VDAGVADataTahoe.hpp", "26.7.1", 1, 1),
    })
    for label, (path, build, expected_records, expected_sites) in page_cases.items():
        text = header_text(path)
        if build not in text:
            raise Failure(f"{label}: build string {build} missing")
        entries, applied, pages = parse_page_patches(text, label)
        if (entries, applied) != (expected_records, expected_sites):
            raise Failure(f"{label}: expected {expected_records} records / {expected_sites} sites, "
                          f"got {entries} / {applied}")
        print(f"{label}: {entries} record(s), {applied} site(s), {len(pages)} page(s)")

    check_compiled_selector()
    print("all multi-version VCN/VDA data checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Failure as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
