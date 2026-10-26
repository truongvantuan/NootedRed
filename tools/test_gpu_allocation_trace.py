#!/usr/bin/env python3
"""Execute the production installer/wrappers under sanitizers, without GPU work."""
from pathlib import Path
import re
import subprocess
import tempfile
import sys

ROOT=Path(__file__).resolve().parents[1]
production=(ROOT/'NootedRed/X5000AllocationTrace.inc').read_text()
prefix=r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <map>
#include <string>
#include <vector>
#include <cstdarg>
#include <cstdio>
#include <GPUAllocationTraceData.hpp>
using mach_vm_address_t=uintptr_t;using proc_t=void*;
template<class T>T& getMember(void* p,size_t n){return *reinterpret_cast<T*>(static_cast<char*>(p)+n);}
#define arrsize(a) (sizeof(a)/sizeof((a)[0]))
#define FunctionCast(f,p) reinterpret_cast<decltype(&f)>(p)
std::vector<std::string> logs;
void traceLog(const char*,const char* f,...){char b[512];va_list a;va_start(a,f);vsnprintf(b,sizeof(b),f,a);va_end(a);logs.emplace_back(b);}
#define SYSLOG(...) traceLog(__VA_ARGS__)
struct IOSimpleLock{bool held=false;} lockObject;
bool lockAvailable=true;
IOSimpleLock* IOSimpleLockAlloc(){return lockAvailable?&lockObject:nullptr;}
void IOSimpleLockLock(IOSimpleLock* p){assert(p && !p->held);p->held=true;}
void IOSimpleLockUnlock(IOSimpleLock* p){assert(p && p->held);p->held=false;}
bool requested=true,identityValid=true,haveProcess=true;int testKernelMajor=24;
bool checkKernelArgument(const char* p){assert(std::string(p)=="-NRedAllocTrace");return requested;}
struct Version{int major()const{return testKernelMajor;}};Version currentKernelVersion(){return {};}
struct NRed{std::map<std::string,UInt32> props;static NRed& singleton(){static NRed x;return x;}void setProp32(const char* k,UInt32 v){props[k]=v;}};
struct CompatTarget{struct Identity{UInt8 uuid[16]{};};static bool parseMachOIdentity(Identity& i,const UInt8* p,size_t n){if(!identityValid||n<16)return false;memcpy(i.uuid,p,16);return true;}};
struct KernelPatcher{std::map<std::string,uintptr_t> symbols;int routes=0,failRoute=-1;uintptr_t solveSymbol(size_t,const char* s,uintptr_t,size_t,bool){return symbols[s];}void clearError(){}};
namespace PenguinWizardry{struct PatternRouteRequest{const char* symbol;uintptr_t from=0,*original;template<class F>PatternRouteRequest(const char* s,F,uintptr_t& p):symbol(s),original(&p){}bool route(KernelPatcher& p,size_t,uintptr_t,size_t){assert(!symbol&&from);if(p.routes++==p.failRoute)return false;*original=from;return true;}};}
struct X5000{uintptr_t orgAllocatePhysical=0,orgResourcePageon=0,orgAllocateLargeBlocks=0;static X5000& singleton(){static X5000 x;return x;}void installAllocationTrace(KernelPatcher&,size_t,uintptr_t,size_t);static bool traceAllocatePhysical(void*);static void traceResourcePageon(void*,void*,bool,UInt64);static bool traceAllocateLargeBlocks(void*,void*,UInt64,UInt64,UInt64,UInt32,UInt32,bool);};
UInt64 tid=9876;
void* current_thread(){return reinterpret_cast<void*>(2);}UInt64 thread_tid(void*){return tid;}
proc_t current_proc(){return haveProcess?reinterpret_cast<void*>(1):nullptr;}
int proc_pid(proc_t p){assert(p);return 6543;}void proc_name(int,char* p,int n){strncpy(p,"WindowServer",n);}
unsigned OSBacktrace(void** p,unsigned n){assert(n>=2);p[0]=reinterpret_cast<void*>(0x12345);p[1]=reinterpret_cast<void*>(0x23456);return 2;}
'''
suffix=r'''
alignas(16) UInt8 image[256],physical[0x140],resource[0x240];
void* expectedEvent=reinterpret_cast<void*>(0x123);
bool physicalResult=false,largeResult=false,nest=false;
int physicalCalls=0,pageonCalls=0,depth=0;
bool originalLarge(void* p,void* element,UInt64 bytes,UInt64 align,UInt64 minimum,UInt32 origin,UInt32 operation,bool noFixed){
 assert(!lockObject.held);assert(p==resource&&element==physical&&bytes==15728640&&align==65536&&minimum==4096);assert(origin==0xfedcba98&&operation==0x87654321&&noFixed);return largeResult;
}
bool originalPhysical(void* p){assert(!lockObject.held);assert(p==physical);++physicalCalls;auto observed=X5000::traceAllocateLargeBlocks(resource,physical,15728640,65536,4096,0xfedcba98,0x87654321,true);assert(observed==largeResult);return physicalResult;}
void originalPageon(void* p,void* event,bool flag,UInt64 options){
 assert(!lockObject.held);assert(p==resource&&event==expectedEvent&&flag&&options==0xfedcba9876543210ULL);++pageonCalls;
 if(nest&&depth++==0){X5000::traceResourcePageon(p,event,flag,options);--depth;}
 else{assert(X5000::traceAllocatePhysical(physical)==physicalResult);if(nest)--depth;}
 getMember<UInt32>(resource,GPUAllocationTraceData::ResourceFlagsOffset)=0x87654321;
}
KernelPatcher fixture(){
 memset(image,0,sizeof(image));memcpy(image,GPUAllocationTraceData::DriverUUID,16);KernelPatcher p;
 for(size_t i=0;i<arrsize(GPUAllocationTraceData::Methods);++i){auto offset=64+i*64;memcpy(image+offset,GPUAllocationTraceData::Methods[i].prefix,32);p.symbols[GPUAllocationTraceData::Methods[i].symbol]=reinterpret_cast<uintptr_t>(image+offset);}
 allocationTrace={};lockObject.held=false;lockAvailable=true;requested=true;identityValid=true;testKernelMajor=24;haveProcess=true;logs.clear();NRed::singleton().props.clear();return p;
}
void install(KernelPatcher& p){X5000::singleton().installAllocationTrace(p,1,reinterpret_cast<uintptr_t>(image),sizeof(image));}
void forwarders(){X5000::singleton().orgAllocatePhysical=reinterpret_cast<uintptr_t>(originalPhysical);X5000::singleton().orgResourcePageon=reinterpret_cast<uintptr_t>(originalPageon);X5000::singleton().orgAllocateLargeBlocks=reinterpret_cast<uintptr_t>(originalLarge);}
int main(){
 auto p=fixture();requested=false;X5000::singleton().installAllocationTrace(p,1,0,0);assert(p.routes==0&&NRed::singleton().props.empty());
 for(int kind=0;kind<8;++kind){p=fixture();if(kind==0)testKernelMajor=25;if(kind==1)identityValid=false;if(kind==2)image[0]^=1;if(kind==3)image[64+17]^=1;if(kind==4)image[128+17]^=1;if(kind==5)image[192+17]^=1;if(kind==6)p.symbols[GPUAllocationTraceData::Methods[1].symbol]=reinterpret_cast<uintptr_t>(image+240);if(kind==7)lockAvailable=false;install(p);assert(!allocationTrace.ready&&p.routes==0);}
 // Partial routing must leave the installed wrapper completely transparent.
 p=fixture();p.failRoute=1;install(p);assert(p.routes==2&&!allocationTrace.ready);forwarders();assert(!X5000::traceAllocatePhysical(physical));assert(logs.size()==1);
 p=fixture();install(p);assert(p.routes==3&&allocationTrace.ready);forwarders();
 getMember<UInt64>(physical,GPUAllocationTraceData::SizeOffset)=15728640;
 getMember<UInt64>(physical,GPUAllocationTraceData::AlignmentOffset)=65536;
 getMember<UInt32>(physical,GPUAllocationTraceData::AllocationFlagsOffset)=0x01080000;
 auto pristinePhysical=std::vector<UInt8>(physical,physical+sizeof(physical));
 getMember<UInt32>(resource,GPUAllocationTraceData::ResourceFlagsOffset)=0x12345678;
 int pc=physicalCalls,rc=pageonCalls;X5000::traceResourcePageon(resource,expectedEvent,true,0xfedcba9876543210ULL);
 assert(physicalCalls==pc+1&&pageonCalls==rc+1&&allocationTrace.failures==1);
 assert(memcmp(physical,pristinePhysical.data(),sizeof(physical))==0);
 assert(logs[1].find("bytes=15728640 align=65536 minBlock=4096")!=std::string::npos);
 assert(logs.back().find("pageon-end")!=std::string::npos&&logs.back().find("outer=1")!=std::string::npos);
 assert(logs.back().find("flagsBefore=0x12345678 flagsAfter=0x87654321")!=std::string::npos);
 // Successful native allocations do not become failures or diagnostic output.
 physicalResult=true;largeResult=true;auto oldLogs=logs.size();pc=physicalCalls;assert(X5000::traceAllocatePhysical(physical));assert(physicalCalls==pc+1&&logs.size()==oldLogs);physicalResult=false;
 // A false physical return after a successful allocator call is not labelled allocation failure.
 oldLogs=logs.size();assert(!X5000::traceAllocatePhysical(physical));assert(logs.size()==oldLogs);largeResult=false;
 // Nested paging belongs to its innermost thread context; all slots release.
 nest=true;depth=0;X5000::traceResourcePageon(resource,expectedEvent,true,0xfedcba9876543210ULL);nest=false;
 for(auto& x:allocationTrace.contexts)assert(x.event==0);
 // Exhausted bookkeeping is not allowed to alter native execution.
 for(size_t i=0;i<GPUAllocationTraceData::ContextCount;++i)assert(allocationTraceBegin(100+i)<GPUAllocationTraceData::ContextCount);
 assert(allocationTraceBegin(tid)==GPUAllocationTraceData::ContextCount);pc=physicalCalls;X5000::traceResourcePageon(resource,expectedEvent,true,0xfedcba9876543210ULL);assert(physicalCalls==pc+1);
 for(size_t i=0;i<GPUAllocationTraceData::ContextCount;++i)allocationTraceEnd(i);
 // Kernel-thread context and a failure flood stay bounded without changing returns.
 haveProcess=false;logs.clear();pc=physicalCalls;for(int i=0;i<10000;++i)assert(!X5000::traceAllocatePhysical(physical));assert(physicalCalls==pc+10000);
 assert(allocationTrace.emitted==GPUAllocationTraceData::MaximumFailures);
 assert(logs.size()<=2*GPUAllocationTraceData::MaximumFailures+4*12+2);
 assert(!lockObject.held);for(auto& x:allocationTrace.contexts)assert(x.event==0);
}
'''
with tempfile.TemporaryDirectory() as temp:
    d=Path(temp);(d/'libkern').mkdir()
    (d/'libkern/OSTypes.h').write_text('#include <cstdint>\n#include <cstddef>\nusing UInt8=uint8_t;using UInt32=uint32_t;using UInt64=uint64_t;\n')
    (d/'test.cpp').write_text(prefix+production+suffix)
    subprocess.run(['xcrun','clang++','-std=c++17','-O1','-fsanitize=address,undefined','-fno-omit-frame-pointer',
        '-I'+str(d),'-I'+str(ROOT/'NootedRed'),str(d/'test.cpp'),'-o',str(d/'test')],check=True)
    subprocess.run([str(d/'test')],check=True)
from gen_vcn_kernel_data import KernelCollection,DEFAULT_KC,X5000_ID
if DEFAULT_KC.exists():
    k=KernelCollection(DEFAULT_KC).kexts[X5000_ID]
    if k.uuid.hex()=='41c43219294b3932b77e68824533e800':
        data=(ROOT/'NootedRed/GPUAllocationTraceData.hpp').read_text()
        methods=re.findall(r'\{"([^"]+)",\s*\{([^}]+)\}\}',data)
        assert len(methods)==3
        for name,values in methods:
            expected=bytes(int(x,16) for x in re.findall(r'0x([0-9A-Fa-f]{2})',values))
            assert len(expected)==32 and k.read(k.symbols[name],32)==expected,name
print('allocation trace: opt-in/UUID/version/full-prefix guards, partial-route transparency, exact native forwarding, nested contexts, no-slot handling and bounded failure flood passed')
