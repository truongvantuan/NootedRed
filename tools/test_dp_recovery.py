#!/usr/bin/env python3
"""Compile and exercise the production DP wake policy and private-entry-point guards.

On this Sonoma host, also validate against the actual stock framebuffer in the KC.
Does not access the running GPU, install a kext, or claim hardware wake is fixed.
"""
from __future__ import annotations

from pathlib import Path
import mmap
import os
import shlex
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PROGRAM = r'''
#include <DPRecovery.hpp>
#include <cassert>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <vector>
using namespace DPRecovery;
struct Reply { int status; uint8_t power; };
struct Sink {
    std::vector<Reply> replies;
    std::vector<int> writes;
    std::vector<unsigned> events;
    unsigned readCount=0, writeCount=0, delayCount=0;
    uint8_t expectedWrite=1;
    Result run() {
        return wakeReceiver([&](uint32_t addr, uint8_t* value, uint32_t count) {
            assert(addr==kSetPower && count==1 && readCount<replies.size());
            events.push_back(1);
            auto reply=replies[readCount++]; *value=reply.power; return reply.status;
        }, [&](uint32_t addr, const uint8_t* value, uint32_t count) {
            assert(addr==kSetPower && count==1 && *value==expectedWrite);
            assert(writeCount<writes.size()); events.push_back(2);
            return writes[writeCount++];
        }, [&](uint32_t ms) { assert(ms==kSettleMs); ++delayCount; events.push_back(3); });
    }
};
void put32(std::vector<uint8_t>& d, size_t off, uint32_t value) {
    for (unsigned i=0;i<4;++i) d[off+i]=value>>(8*i);
}
std::vector<uint8_t> validImage() {
    std::vector<uint8_t> d(kWriteDpcdOffset+sizeof(kWriteDpcdPrologue));
    put32(d,0,0xFEEDFACF); put32(d,4,0x01000007);
    put32(d,16,1); put32(d,20,24); put32(d,32,0x1B); put32(d,36,24);
    memcpy(d.data()+40,kFramebufferUuid,16);
    memcpy(d.data()+kEnablePhyOffset,kEnablePhyPrologue,sizeof(kEnablePhyPrologue));
    memcpy(d.data()+kReadDpcdOffset,kReadDpcdPrologue,sizeof(kReadDpcdPrologue));
    memcpy(d.data()+kWriteDpcdOffset,kWriteDpcdPrologue,sizeof(kWriteDpcdPrologue));
    return d;
}
int main(int argc, char** argv) {
    { Sink s{{{1,1}}, {}}; auto r=s.run(); assert(r.state==State::AlreadyAwake && !s.writeCount && !s.delayCount); }
    { Sink s{{{1,2},{1,1}},{1}}; auto r=s.run(); assert(r.state==State::Woken && r.attempts==1 && r.before==2 && r.after==1);
      assert((s.events==std::vector<unsigned>{1,2,3,1})); }
    { Sink s{{{1,0xA5},{1,0xA1}},{1}}; s.expectedWrite=0xA1; auto r=s.run(); assert(r.state==State::Woken); }
    { Sink s{{{1,0xA2},{1,0xA1}},{1}}; s.expectedWrite=0xA1; auto r=s.run(); assert(r.state==State::Woken); }
    { Sink s{{{0,2},{0,2},{0,2}}, {}}; auto r=s.run(); assert(r.state==State::ReadFailed && s.readCount==3 && s.delayCount==2 && !s.writeCount); }
    { Sink s{{{-1,0},{1,1}}, {}}; auto r=s.run(); assert(r.state==State::AlreadyAwake && s.delayCount==1); }
    { Sink s{{{1,2}}, {0,0,0}}; auto r=s.run(); assert(r.state==State::WakeFailed && s.readCount==1 && s.writeCount==3 && s.delayCount==3); }
    { Sink s{{{1,2},{1,2},{1,2},{1,2}}, {1,1,1}}; auto r=s.run(); assert(r.state==State::WakeFailed && s.writeCount==3); }
    { Sink s{{{1,2},{0,1},{1,1}}, {1,1}}; auto r=s.run(); assert(r.state==State::Woken && r.attempts==2); }
    { Sink s{{{1,2},{0,1},{0,1},{0,1}}, {1,1,1}}; auto r=s.run(); assert(r.state==State::WakeFailed); }
    for (uint8_t power : {0,3,4,6,7}) {
        Sink s{{{1,power}}, {}}; assert(s.run().state==State::UnsupportedPower && !s.writeCount && !s.delayCount);
    }
    auto image=validImage(); assert(matchesFramebuffer(image.data(),image.size()));
    assert(!matchesFramebuffer(nullptr,image.size()));
    for (size_t size : {size_t(0),size_t(31),size_t(55),image.size()-1}) assert(!matchesFramebuffer(image.data(),size));
    for (size_t off : {size_t(0),size_t(4),size_t(40),kEnablePhyOffset,kReadDpcdOffset,kWriteDpcdOffset}) {
        auto bad=image; bad[off]^=1; assert(!matchesFramebuffer(bad.data(),bad.size()));
    }
    for (uint32_t size : {0U,4U,25U,0xFFFFFFFFU}) {
        auto bad=image; put32(bad,36,size); assert(!matchesFramebuffer(bad.data(),bad.size()));
    }
    { auto bad=image; put32(bad,16,0xFFFFFFFFU); assert(!matchesFramebuffer(bad.data(),bad.size())); }
    { auto bad=image; put32(bad,20,0xFFFFFFFFU); assert(!matchesFramebuffer(bad.data(),bad.size())); }
    { auto bad=image; put32(bad,16,2); put32(bad,20,48); memcpy(bad.data()+56,bad.data()+32,24);
      assert(!matchesFramebuffer(bad.data(),bad.size())); }
    if (argc>=2) {
        std::ifstream f(argv[1],std::ios::binary); assert(f);
        std::vector<uint8_t> real((std::istreambuf_iterator<char>(f)),{});
        if (argc==2) {
            assert(matchesFramebuffer(real.data(),real.size()));
            std::puts("Installed framebuffer UUID and all three private entry-point guards: PASS");
        } else {
            assert(!matchesFramebuffer(real.data(),real.size()));
            std::puts("Different installed framebuffer correctly refused: PASS");
        }
    }
    std::puts("Production DP wake policy (15 cases) and malformed/mismatched image rejection: PASS");
}
'''


def stock_framebuffer(kc: Path) -> bytes | None:
    if not kc.is_file():
        return None
    with kc.open("rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
        if struct.unpack_from("<I", data)[0] != 0xFEEDFACF:
            return None
        at = 32
        for _ in range(struct.unpack_from("<I", data, 16)[0]):
            command, size = struct.unpack_from("<II", data, at)
            if command == 0x80000035:
                _, offset, name_offset, _ = struct.unpack_from("<QQII", data, at + 8)
                name = data[at + name_offset:at + size].split(b"\0")[0]
                if name == b"com.apple.kext.AMDRadeonX6000Framebuffer":
                    pos = offset + 32
                    for _ in range(struct.unpack_from("<I", data, offset + 16)[0]):
                        cmd, length = struct.unpack_from("<II", data, pos)
                        if cmd == 0x19 and data[pos+8:pos+24].split(b"\0")[0] == b"__TEXT":
                            _, _, file_offset, file_size = struct.unpack_from("<QQQQ", data, pos+24)
                            return bytes(data[file_offset:file_offset+file_size])
                        pos += length
            at += size
    return None


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="nred-dp-test-") as folder:
        temp = Path(folder)
        src = temp / "test.cpp"
        src.write_text(PROGRAM)
        executable = temp / "test"
        compiler = shlex.split(os.environ.get("CXX", "clang++"))
        subprocess.run(compiler + ["-std=c++17", "-Wall", "-Wextra", "-Werror", "-Wno-missing-field-initializers",
                                  "-fsanitize=address,undefined", "-I", str(ROOT / "NootedRed"),
                                  str(src), "-o", str(executable)], check=True)
        args = [str(executable)]
        real = stock_framebuffer(Path("/System/Library/KernelCollections/SystemKernelExtensions.kc"))
        if real:
            image = temp / "stock-framebuffer.bin"
            image.write_bytes(real)
            args.append(str(image))
            at = 32
            uuid = None
            for _ in range(struct.unpack_from("<I", real, 16)[0]):
                cmd, size = struct.unpack_from("<II", real, at)
                if cmd == 0x1B:
                    uuid = real[at+8:at+24].hex()
                at += size
            if uuid != "2a0ec5c373553063bccee15cf7e02a0c":
                args.append("--expect-rejection")
        subprocess.run(args, check=True)


if __name__ == "__main__":
    main()
