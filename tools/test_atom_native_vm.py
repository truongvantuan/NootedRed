#!/usr/bin/env python3
"""Run the inspected stock ATOM VM on synthetic BIOS tables, entirely in userspace.

No GPU, IOKit user client, kernel patch or installed EFI is accessed. Only audited
interpreter/branch/CallTable code is copied. Allocation, operand decoding and the
test register operation are host callbacks. This validates the real EOT cleanup
path but does not validate kernel routing or physical DisplayPort recovery.
"""
from pathlib import Path
import platform
import struct
import subprocess
import tempfile

from test_dp_recovery import stock_framebuffer

ROOT = Path(__file__).resolve().parents[1]
PROGRAM = r'''
#include <DPRecovery.hpp>
#include <AtomLoopGuard.hpp>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <vector>
#include <sys/mman.h>
using namespace DPRecovery;
static uint64_t canary=0x12345678abcdef00ULL;
static unsigned allocated,freed,branches,reads;
static AtomExecution* guard;
static void (*nativeJump)(void*);
static void* allocateFrame(void*,size_t size) { ++allocated; return calloc(1,size); }
static void freeFrame(void*,void* frame) { ++freed; free(frame); }
static void decodeOperands(void*) {} // Test opcodes use no decoded operands.
static void readTestRegister(void* context) {
    ++reads;
    auto* bytes=static_cast<uint8_t*>(context);
    bytes[0x48]=2; // Not equal: the finite fixture's JEQ falls through.
    auto* frame=atomLoad<AtomFrame*>(context,8);
    ++frame->instruction;
    if(guard) { guard->lastRegister=0x1234; guard->lastValue=0; }
}
static void jumpWithGuard(void* context) {
    if(guard && guard->checkBranch(context,++branches)) return;
    nativeJump(context);
}
template<typename T> static void store(uint8_t* p,size_t at,T value) { memcpy(p+at,&value,sizeof(value)); }
static void trampoline(uint8_t* image,size_t at,uintptr_t target) {
    image[at]=0x48; image[at+1]=0xB8; store(image,at+2,target); // movabs target,rax
    image[at+10]=0xFF; image[at+11]=0xE0; // jmp rax
}
static void entry(uint8_t* image,unsigned opcode,uintptr_t target,uint8_t argument=0) {
    store(image,0x2B9680+opcode*10,target);
    image[0x2B9680+opcode*10+8]=argument;
}
int main(int argc,char** argv) {
    assert(argc==2);
    std::ifstream file(argv[1],std::ios::binary); assert(file);
    std::vector<uint8_t> stock((std::istreambuf_iterator<char>(file)),{});
    assert(matchesFramebuffer(stock.data(),stock.size()));
    assert(matchesAtomEntryPoints(stock.data(),stock.size()));
    constexpr size_t arenaSize=0x2C0000;
    auto* image=static_cast<uint8_t*>(mmap(nullptr,arenaSize,PROT_READ|PROT_WRITE,
                                         MAP_PRIVATE|MAP_ANON,-1,0));
    assert(image!=MAP_FAILED);
    // The frame lifecycle, instruction dispatch, branch and CallTable operations
    // below are the original stock instructions, with their relative layout kept.
    for(auto range: {std::pair<size_t,size_t>{0x5C400,0x367}, {0x5C9F0,0x3B},
                    {0x5C1B0,0x40}, {0x5C120,0x80}, {0x5C350,0xB0}}) {
        memcpy(image+range.first,stock.data()+range.first,range.second);
    }
    trampoline(image,0x5A550,reinterpret_cast<uintptr_t>(allocateFrame));
    trampoline(image,0x5A570,reinterpret_cast<uintptr_t>(freeFrame));
    trampoline(image,0x5A980,reinterpret_cast<uintptr_t>(decodeOperands));
    trampoline(image,0x5A5A0,reinterpret_cast<uintptr_t>(abort));
    // Redirect only the stack-canary failure call to the host's abort routine.
    store(image,0x5C762,int32_t(0x5A5A0-(0x5C761+5)));
    store(image,0x28A128,reinterpret_cast<uintptr_t>(&canary));
    nativeJump=reinterpret_cast<void(*)(void*)>(image+0x5C1B0);
    entry(image,0x4A,reinterpret_cast<uintptr_t>(readTestRegister));
    entry(image,0x43,reinterpret_cast<uintptr_t>(jumpWithGuard),5);
    entry(image,0x44,reinterpret_cast<uintptr_t>(jumpWithGuard),1);
    entry(image,0x52,reinterpret_cast<uintptr_t>(image+0x5C120));
    assert(mprotect(image,arenaSize,PROT_READ|PROT_EXEC)==0);
    using Execute=bool(void*,uint32_t,void*,uint32_t);
    auto* execute=reinterpret_cast<Execute*>(image+0x5C9F0);
    for(unsigned depth: {1U,3U,64U}) for(bool loop: {false,true}) {
        std::vector<uint8_t> bios(0x10000),parameters(4096);
        store(bios.data(),0x48,uint16_t(0x80));
        store(bios.data(),0x80+0x1E,uint16_t(0x400));
        store(bios.data(),0x80+0x20,uint16_t(0x800));
        store(bios.data(),0x800+0x32,uint16_t(0x900));
        for(unsigned n=0;n<depth;++n) {
            const unsigned offset=0x1000+n*64;
            store(bios.data(),0x404+(0x4C+n)*2,uint16_t(offset));
            auto* table=bios.data()+offset;
            store(table,0,uint16_t(n+1==depth?11:9)); table[5]=4;
            if(n+1<depth) { table[6]=0x52; table[7]=0x4C+n+1; table[8]=0x5B; }
            else { table[6]=0x4A; table[7]=loop?0x43:0x44;
                   store(table,8,uint16_t(6)); table[10]=0x5B; }
        }
        uint8_t self[32]{};
        store(self,0x10,bios.data());
        allocated=freed=branches=reads=0;
        AtomExecution execution{1000}; guard=&execution;
        const bool nativeResult=execute(self,0x4C,parameters.data(),1);
        guard=nullptr;
        // EOT is a native success even after redirection. Production's outer
        // wrapper must return failure when execution.aborted is set.
        assert(nativeResult && execution.aborted==loop && !execution.unwindRefused);
        assert(allocated==depth && freed==depth);
        assert(reads==(loop?1000U:1U));
        assert(branches==(loop?1000U:1U));
        if(loop) assert(execution.tableOffset==0x1000+(depth-1)*64 && execution.instructionOffset==7);
        // Invoke the same inner VM directly so the original execution context's
        // parameter pointer can be inspected after its native CallTable/EOT path.
        uint8_t executionContext[32]{};
        store(executionContext,0,parameters.data());
        store(executionContext,0x10,bios.data());
        allocated=freed=branches=reads=0;
        AtomExecution directGuard{1000}; guard=&directGuard;
        using InnerExecute=int(void*,uint32_t);
        auto* inner=reinterpret_cast<InnerExecute*>(image+0x5C400);
        assert(inner(executionContext,0x4C)==0);
        guard=nullptr;
        assert(atomLoad<uint8_t*>(executionContext,0)==parameters.data());
        assert(allocated==depth && freed==depth && directGuard.aborted==loop);
        printf("Stock VM: depth=%u loop=%u frames allocated/freed=%u/%u: PASS\n",
               depth,loop,allocated,freed);
    }
    assert(munmap(image,arenaSize)==0);
}
'''


def main():
    if platform.machine() != "x86_64":
        print("SKIP: inspected interpreter is x86_64")
        return
    image = stock_framebuffer(Path("/System/Library/KernelCollections/SystemKernelExtensions.kc"))
    if not image:
        print("SKIP: stock framebuffer unavailable")
        return
    at, uuid = 32, None
    for _ in range(struct.unpack_from("<I", image, 16)[0]):
        command, size = struct.unpack_from("<II", image, at)
        if command == 0x1B:
            uuid = image[at + 8:at + 24].hex()
        at += size
    if uuid != "2a0ec5c373553063bccee15cf7e02a0c":
        print("SKIP: stock framebuffer is outside the inspected UUID")
        return
    with tempfile.TemporaryDirectory(prefix="nred-native-atom-") as directory:
        temp = Path(directory)
        source, binary, stock = temp / "test.cpp", temp / "test", temp / "stock.bin"
        source.write_text(PROGRAM)
        stock.write_bytes(image)
        subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        "-I", str(ROOT / "NootedRed"), str(source), "-o", str(binary)], check=True)
        subprocess.run([str(binary), str(stock)], check=True, timeout=10)


if __name__ == "__main__":
    main()
