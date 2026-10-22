#!/usr/bin/env python3
"""Exercise the production ATOM unwind policy, thread isolation and stock-image guards.

This is a host test. It cannot establish kernel ABI correctness, link training,
or physical monitor recovery; hardware verification remains required.
"""
from pathlib import Path
import os
import shlex
import struct
import subprocess
import tempfile

from test_dp_recovery import stock_framebuffer

ROOT = Path(__file__).resolve().parents[1]
PROGRAM = r'''
#include <AtomLoopGuard.hpp>
#include <cassert>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <thread>
#include <vector>
using namespace DPRecovery;
template<typename T> void put(void* p, size_t offset, T value) {
    memcpy(static_cast<uint8_t*>(p)+offset, &value, sizeof(value));
}
struct Fixture {
    std::vector<uint8_t> bios = std::vector<uint8_t>(0x10000);
    uint8_t execution[32]{};
    uint8_t context[0x60]{};
    std::vector<AtomFrame*> frames;
    Fixture(unsigned depth=3) {
        put(execution,0x10,bios.data()); put(context,0,static_cast<void*>(execution));
        AtomFrame* parent=nullptr;
        for (unsigned i=0;i<depth;++i) {
            auto* table=bios.data()+64+i*64;
            put(table,0,uint16_t(32)); table[5]=4;
            auto* frame=new AtomFrame{table,table+8,nullptr,parent};
            frames.push_back(frame); parent=frame;
        }
        put(context,8,parent);
        put(context,0x10,uint32_t(0x1234)); put(context,0x14,uint32_t(0x5678));
    }
    ~Fixture() { for (auto* frame:frames) delete frame; }
    // Model just the inspected original EOT pop/free path, not the watchdog.
    // It must free every frame and restore the parameter stack naturally.
    unsigned nativeEotCleanup(unsigned& parameterTop) {
        auto* frame=atomLoad<AtomFrame*>(context,8);
        unsigned freed=0;
        while(frame) {
            assert(*frame->instruction==0x5B);
            auto* parent=frame->parent;
            auto it=std::find(frames.begin(),frames.end(),frame);
            assert(it!=frames.end()); frames.erase(it); delete frame; ++freed;
            frame=parent;
            if (parent) parameterTop-=parent->table[5]&0x7C;
        }
        put(context,8,static_cast<AtomFrame*>(nullptr));
        return freed;
    }
};
int main(int argc,char** argv) {
    { Fixture f; AtomExecution e{100}; auto* ip=f.frames.back()->instruction;
      assert(!e.checkBranch(f.context,99) && !e.aborted && f.frames.back()->instruction==ip);
      e.lastRegister=0x123; e.lastValue=0x456;
      assert(e.checkBranch(f.context,100) && e.aborted && !e.unwindRefused);
      assert(e.tableOffset==192 && e.instructionOffset==8);
      assert(e.compareSource==0x1234 && e.compareDestination==0x5678);
      assert(e.lastRegister==0x123 && e.lastValue==0x456);
      assert(!e.checkBranch(f.context,101));
      unsigned top=32; assert(f.nativeEotCleanup(top)==3 && top==24 && f.frames.empty()); }
    { Fixture f(1); AtomExecution e{1}; assert(e.checkBranch(f.context,2));
      unsigned top=32; assert(f.nativeEotCleanup(top)==1 && top==32); }
    { Fixture f(64); AtomExecution e{1}; assert(e.checkBranch(f.context,2));
      unsigned top=256; assert(f.nativeEotCleanup(top)==64 && top==4); }
    { Fixture f(65); auto* ip=f.frames.back()->instruction; AtomExecution e{1};
      assert(!e.checkBranch(f.context,2) && e.unwindRefused && !e.aborted);
      assert(f.frames.back()->instruction==ip); }
    { Fixture f; auto* ip=f.frames.back()->instruction; f.frames.front()->parent=f.frames.back();
      AtomExecution e{1}; assert(!e.checkBranch(f.context,2) && e.unwindRefused);
      for(auto* frame:f.frames) assert(frame->instruction==frame->table+8);
      assert(f.frames.back()->instruction==ip); }
    { Fixture f; f.frames.front()->instruction=f.frames.front()->table+32;
      AtomExecution e{1}; assert(!e.checkBranch(f.context,2) && e.unwindRefused);
      assert(f.frames.back()->instruction==f.frames.back()->table+8); }
    { Fixture f; f.frames.front()->table=f.bios.data()+0xFFFF;
      AtomExecution e{1}; assert(!e.checkBranch(f.context,2) && e.unwindRefused); }
    { Fixture f; put(f.bios.data()+64,0,uint16_t(0xFFFF));
      AtomExecution e{1}; assert(!e.checkBranch(f.context,2) && e.unwindRefused); }
    { Fixture f(0); AtomExecution e{1}; assert(!e.checkBranch(f.context,2) && e.unwindRefused); }
    { AtomExecution e{1}; assert(!e.checkBranch(nullptr,2) && e.unwindRefused);
      assert(!unwindAtomFrames(nullptr)); }
    { Fixture f; put(f.context,0,static_cast<void*>(nullptr)); AtomExecution e{1};
      assert(!e.checkBranch(f.context,2) && e.unwindRefused); }
    { AtomThreadSlots<2> slots; assert(!slots.acquire(0));
      auto* a=slots.acquire(1); auto* b=slots.acquire(2);
      assert(a && b && a!=b && !slots.acquire(3));
      AtomExecution ea{1},eb{2}; a->execution=&ea; b->execution=&eb;
      assert(slots.find(1)->execution==&ea && slots.find(2)->execution==&eb);
      assert(slots.acquire(1)==a && a->depth==2); slots.release(a);
      assert(slots.find(1)==a && a->execution==&ea && a->depth==1);
      slots.release(a); assert(!slots.find(1)); slots.release(b);
      a=slots.acquire(3); assert(a && !a->execution); slots.release(a); }
    { AtomThreadSlots<16> slots; std::vector<std::thread> workers;
      for(uintptr_t id=1;id<=8;++id) workers.emplace_back([&,id] {
          for(unsigned n=0;n<2000;++n) {
              auto* s=slots.acquire(id); assert(s); AtomExecution e{n}; s->execution=&e;
              assert(slots.find(id)==s && slots.find(id)->execution==&e); slots.release(s);
          }
      });
      for(auto& worker:workers) worker.join(); }
    assert(!matchesAtomEntryPoints(nullptr,0x100000));
    if(argc==2) {
        std::ifstream f(argv[1],std::ios::binary); assert(f);
        std::vector<uint8_t> image((std::istreambuf_iterator<char>(f)),{});
        assert(matchesAtomEntryPoints(image.data(),image.size()));
        for(const auto& guard:kAtomEntryGuards) {
            auto bad=image; bad[guard.offset]^=1;
            assert(!matchesAtomEntryPoints(bad.data(),bad.size()));
            assert(!matchesAtomEntryPoints(image.data(),guard.offset+31));
        }
        auto bad=image; bad[0x5C6EC]^=1;
        assert(!matchesAtomEntryPoints(bad.data(),bad.size()));
        std::puts("Installed ATOM entries and complete interpreter body: PASS");
    }
    std::puts("Native EOT cleanup, malformed-chain refusal, timeout and thread isolation: PASS");
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix="nred-atom-test-") as directory:
        temp = Path(directory)
        src = temp / "test.cpp"
        # std::find is deliberately confined to this host-only cleanup model.
        src.write_text("#include <algorithm>\n" + PROGRAM)
        binary = temp / "test"
        compiler = shlex.split(os.environ.get("CXX", "c++"))
        subprocess.run(compiler + ["-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
                                  "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                                  "-I", str(ROOT / "NootedRed"), str(src), "-o", str(binary)], check=True)
        args = [str(binary)]
        image = stock_framebuffer(Path("/System/Library/KernelCollections/SystemKernelExtensions.kc"))
        if image:
            # Only this exact stock build supports these entry points.
            at, uuid = 32, None
            for _ in range(struct.unpack_from("<I", image, 16)[0]):
                command, size = struct.unpack_from("<II", image, at)
                if command == 0x1B:
                    uuid = image[at + 8:at + 24].hex()
                at += size
            if uuid == "2a0ec5c373553063bccee15cf7e02a0c":
                path = temp / "stock.bin"
                path.write_bytes(image)
                args.append(str(path))
        subprocess.run(args, check=True)


if __name__ == "__main__":
    main()
