#!/usr/bin/env python3
"""Execute production VDA option parsing and external-GPU gating with host stubs."""

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

from test_patch_dispatch import method

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = (ROOT / "NootedRed/VDA.cpp").read_text()
    constants = "\n".join(re.findall(r'const char\* const kBootArg\w+\s*=\s*"[^"]+";', source))
    gate = re.search(r'bool\s+hasExternalVideo\(\) const \{[^}]+\}',
                     (ROOT / "NootedRed/NRed.hpp").read_text()).group()
    program = r'''
#include <cassert>
#include <string>
#include <cstring>
#include <UserSubmitGuard.hpp>
#include <VideoPolicy.hpp>
#define DBGLOG(...) do {} while (0)
const char* args = "";
bool checkKernelArgument(const char* arg) {
    return (std::string(" ") + args + " ").find(std::string(" ") + arg + " ") != std::string::npos;
}
struct VDA {
    bool requested = false, avcOnly = false, hevcEncodeAllowed = false, hevc10Allowed = false;
    void init();
};
'''
    program += constants + method(source, "void VDA::init()")
    program += "struct GPU { bool externalVideo, forceVDA; " + gate + " };\n"
    program += r'''
int main() {
    using namespace UserSubmitGuardData;
    assert(getMethodOffset(23) && getMethodOffset(24) && getMethodOffset(25));
    assert(!getMethodOffset(22) && !getMethodOffset(26));
    UInt64 continuation;
    std::memcpy(&continuation, Payload + PayloadJumpOffset, sizeof(continuation));
    assert(continuation == 0x1122334455667788ULL);

    struct Case { const char* flags; bool requested, avc, encode; };
    for (const auto c : {
        Case{"", true, false, true},
        Case{"-NRedVDA", true, false, true},
        Case{"-NRedNoVDA", false, false, false},
        Case{"-NRedNoVDA -NRedVDA -NRedAVCEncode", false, false, false},
        Case{"-NRedNoHEVC", true, true, false},
        Case{"-NRedNoHEVC -NRedAVCEncode", true, true, false},
        Case{"-NRedAVC", true, true, false},
        Case{"-NRedAVCEncode", true, true, true},
        Case{"-NRedVDA -NRedAVC", true, true, false},
        Case{"-NRedVDA -NRedAVCEncode", true, true, true},
        Case{"-NRedAVC -NRedAVCEncode", true, true, false},
        Case{"-NRedVDA -NRedAVC -NRedAVCEncode", true, true, false}}) {
        args = c.flags;
        VDA v; v.init();
        assert(v.requested == c.requested && v.avcOnly == c.avc && v.hevcEncodeAllowed == c.encode);
    }
    for (const char* flags : {"-NRedHEVC10", "-NRedVDA -NRedHEVC10", "-NRedAVC -NRedHEVC10"}) {
        args=flags; VDA v; v.init(); assert(v.hevc10Allowed == !v.avcOnly);
        assert(v.requested);
    }
    assert(!(GPU{false, false}.hasExternalVideo()));
    assert(!(GPU{false, true}.hasExternalVideo()));
    assert((GPU{true, false}.hasExternalVideo()));
    assert(!(GPU{true, true}.hasExternalVideo()));
}
'''
    with tempfile.TemporaryDirectory(prefix="nred-video-") as directory:
        path = Path(directory)
        (path / "IOKit").mkdir()
        (path / "mach").mkdir()
        (path / "IOKit/IOTypes.h").write_text(
            "#pragma once\n#include <cstdint>\nusing UInt8=uint8_t; using UInt32=uint32_t; using UInt64=uint64_t;\n")
        (path / "mach/mach_types.h").write_text("#pragma once\n")
        (path / "test.cpp").write_text(program)
        compiler = shlex.split(os.environ.get("CXX", "c++"))
        subprocess.run(compiler + ["-std=c++17", "-I" + str(path), "-I" + str(ROOT / "NootedRed"), str(path / "test.cpp"), "-o", str(path / "test")], check=True)
        subprocess.run([str(path / "test")], check=True)
    print("production video modes: eight flag combinations and four external-GPU gates passed")


if __name__ == "__main__":
    main()
