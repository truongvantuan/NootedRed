#!/usr/bin/env python3
"""Exercise the production diagnostic installer and forwarding wrappers without GPU access."""
from pathlib import Path
import re
import subprocess
import tempfile
import sys

ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'NootedRed/X5000.cpp').read_text()
start=source.index('void X5000::installVMTrace(')
end=source.index('// Replaces SDMA1 field',start)
production=source[start:end]
prefix=r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <map>
#include <string>
#include <vector>
#include <cstdarg>
#include <cstdio>
#include <GPUVMTraceData.hpp>
using mach_vm_address_t=uintptr_t;
using proc_t=void*;
template<class T> T& getMember(void* p,size_t o) { return *reinterpret_cast<T*>(static_cast<char*>(p)+o); }
#define arrsize(a) (sizeof(a)/sizeof((a)[0]))
#define FunctionCast(f,p) reinterpret_cast<decltype(&f)>(p)
int logs=0; std::vector<std::string> messages;
void logMessage(const char*,const char* format,...) {
 char buffer[256];va_list args;va_start(args,format);std::vsnprintf(buffer,sizeof(buffer),format,args);va_end(args);
 ++logs;messages.emplace_back(buffer);
}
#define SYSLOG(...) logMessage(__VA_ARGS__)
int OSIncrementAtomic(volatile UInt32* p) { int old=*p; *p=old+1; return old; }
bool requested=true,identityValid=true; int testKernelMajor=24;
bool checkKernelArgument(const char* a) { assert(std::string(a)=="-NRedVMTrace"); return requested; }
struct Version { int major() const { return testKernelMajor; } };
Version currentKernelVersion() { return {}; }
struct NRed {
 std::map<std::string,UInt32> props;
 static NRed& singleton() { static NRed n; return n; }
 void setProp32(const char* key,UInt32 value) { props[key]=value; }
};
struct CompatTarget {
 struct Identity { UInt8 uuid[16]{}; };
 static bool parseMachOIdentity(Identity& i,const UInt8* p,size_t n) {
  if(!identityValid || n<16)return false; std::memcpy(i.uuid,p,16);return true;
 }
};
struct KernelPatcher {
 std::map<std::string,uintptr_t> symbols;
 int routes=0,failRoute=-1;
 uintptr_t solveSymbol(size_t,const char* name,uintptr_t,size_t,bool) { return symbols[name]; }
 void clearError() {}
};
namespace PenguinWizardry {
struct PatternRouteRequest {
 const char* symbol; uintptr_t from=0; uintptr_t* original;
 template<class F> PatternRouteRequest(const char* s,F,uintptr_t& o):symbol(s),original(&o) {}
 bool route(KernelPatcher& p,size_t,uintptr_t,size_t) {
  assert(!symbol && from); const int n=p.routes++; if(n==p.failRoute)return false;
  *original=from;return true;
 }
};
}
struct X5000 {
 uintptr_t orgAssignGPUVirtualAddress=0,orgCommitGPUPageTable=0,orgUpdateGPUPageTable=0;
 uintptr_t orgMapGPUVirtualRange=0,orgGetPTEValue=0;
 static X5000& singleton() { static X5000 x; return x; }
 void installVMTrace(KernelPatcher&,size_t,uintptr_t,size_t);
 static bool traceAssignGPUVirtualAddress(void*,UInt64);
 static bool traceCommitGPUPageTable(void*);
 static bool traceUpdateGPUPageTable(void*);
 static bool traceMapGPUVirtualRange(void*,UInt64,void*,UInt64,UInt64,UInt32);
 static UInt64 traceGetPTEValue(void*,UInt32,UInt64,UInt32,UInt32);
};
std::string processName="gl_blend_probe";
proc_t current_proc() { return reinterpret_cast<void*>(1); }
int proc_pid(proc_t p) { assert(p); return 4321; }
void proc_name(int pid,char* name,int size) { assert(pid==4321);std::strncpy(name,processName.c_str(),size); }
void* current_thread() { return reinterpret_cast<void*>(2); }
UInt64 thread_tid(void* thread) { assert(thread==reinterpret_cast<void*>(2));return 987654321; }
void* expectedSelf; UInt64 expectedAddress; bool nativeResult; int assigns=0,commits=0,updates=0;
bool assignNative(void* self,UInt64 address) {
 assert(self==expectedSelf && address==expectedAddress);++assigns;
 if(nativeResult)getMember<UInt64>(self,GPUVMTraceData::GPUAddressOffset)=address;
 return nativeResult;
}
bool commitNative(void* self) { assert(self==expectedSelf);++commits;return nativeResult; }
bool updateNative(void* self) { assert(self==expectedSelf);++updates;return nativeResult; }
void* expectedMemory;UInt64 expectedOffset,expectedSize,expectedPTE;UInt32 expectedFlags,expectedLevel,expectedFragment;
int ranges=0,ptes=0;
bool rangeNative(void* self,UInt64 address,void* memory,UInt64 offset,UInt64 size,UInt32 flags) {
 assert(self==expectedSelf && address==expectedAddress && memory==expectedMemory);
 assert(offset==expectedOffset && size==expectedSize && flags==expectedFlags);++ranges;return nativeResult;
}
UInt64 pteNative(void* self,UInt32 level,UInt64 address,UInt32 flags,UInt32 fragment) {
 assert(self==expectedSelf && level==expectedLevel && address==expectedAddress);
 assert(flags==expectedFlags && fragment==expectedFragment);++ptes;return expectedPTE;
}
'''
suffix=r'''
int main() {
 alignas(16) UInt8 image[4096]{};
 auto makePatcher=[&]() {
  std::memset(image,0,sizeof(image)); std::memcpy(image,GPUVMTraceData::DriverUUID,16);
  KernelPatcher p;
  for(size_t i=0;i<arrsize(GPUVMTraceData::Methods);i++) {
   auto address=reinterpret_cast<uintptr_t>(image+512+i*128);
   std::memcpy(reinterpret_cast<void*>(address),GPUVMTraceData::Methods[i].prefix,32);
   p.symbols[GPUVMTraceData::Methods[i].symbol]=address;
  }
  NRed::singleton().props.clear(); return p;
 };
 auto install=[&](KernelPatcher& p) { X5000::singleton().installVMTrace(p,1,reinterpret_cast<uintptr_t>(image),sizeof(image)); };
 auto p=makePatcher();requested=false;install(p);assert(p.routes==0 && NRed::singleton().props.empty());requested=true;
 p=makePatcher();image[0]^=1;install(p);assert(p.routes==0 && NRed::singleton().props["NRedVMTraceRejected"]==1);
 p=makePatcher();testKernelMajor=25;install(p);assert(p.routes==0);testKernelMajor=24;
 p=makePatcher();identityValid=false;install(p);assert(p.routes==0);identityValid=true;
 for(size_t bad=0;bad<arrsize(GPUVMTraceData::Methods);bad++) {
  p=makePatcher();image[512+bad*128+24]^=1;install(p);
  assert(p.routes==0 && NRed::singleton().props["NRedVMTraceRejected"]==2);
  p=makePatcher();p.symbols[GPUVMTraceData::Methods[bad].symbol]=reinterpret_cast<uintptr_t>(image+4095);
  install(p);assert(p.routes==0);
 }
 p=makePatcher();install(p);assert(p.routes==5 && NRed::singleton().props["NRedVMTraceEnabled"]==1);
 assert(NRed::singleton().props["NRedVMTraceRoutes"]==GPUVMTraceData::RequiredRoutes);
 assert(NRed::singleton().props["NRedVMTraceVersion"]==2);
 for(int failed=0;failed<5;failed++) {
  p=makePatcher();p.failRoute=failed;install(p);
  assert(p.routes==failed+1 && NRed::singleton().props["NRedVMTraceRoutes"]==((1U<<failed)-1));
  assert(NRed::singleton().props["NRedVMTraceEnabled"]==0);
 }
 auto& x=X5000::singleton();x.orgAssignGPUVirtualAddress=reinterpret_cast<uintptr_t>(assignNative);
 x.orgCommitGPUPageTable=reinterpret_cast<uintptr_t>(commitNative);x.orgUpdateGPUPageTable=reinterpret_cast<uintptr_t>(updateNative);
 x.orgMapGPUVirtualRange=reinterpret_cast<uintptr_t>(rangeNative);x.orgGetPTEValue=reinterpret_cast<uintptr_t>(pteNative);
 alignas(16) UInt8 object[0x180]{}; expectedSelf=object;expectedAddress=0x400004000ULL;
 getMember<UInt64>(object,GPUVMTraceData::GPUAddressOffset)=expectedAddress;
 getMember<UInt32>(object,GPUVMTraceData::OptionsOffset)=0x12345678;
 UInt8 original[sizeof(object)];std::memcpy(original,object,sizeof(object));
 for(bool result:{false,true}) {
  nativeResult=result;int old=logs;
  assert(X5000::traceAssignGPUVirtualAddress(object,expectedAddress)==result);
  assert(X5000::traceCommitGPUPageTable(object)==result);
  assert(X5000::traceUpdateGPUPageTable(object)==result);
  assert(logs-old==6 && std::memcmp(original,object,sizeof(object))==0);
  assert(messages.back().find(result ? "result=1" : "result=0")!=std::string::npos);
  assert(messages.back().find("gpuVA=0x400004000 options=0x12345678")!=std::string::npos);
 }
 assert(assigns==2 && commits==2 && updates==2);
 expectedMemory=reinterpret_cast<void*>(0x1234);expectedOffset=0x100000012ULL;expectedSize=8192;expectedFlags=0x17;
 expectedAddress=0x400000000ULL;
 for(bool result:{false,true}) {
  nativeResult=result;int old=logs;
  assert(X5000::traceMapGPUVirtualRange(object,expectedAddress,expectedMemory,expectedOffset,expectedSize,expectedFlags)==result);
  assert(logs-old==2 && std::memcmp(original,object,sizeof(object))==0);
  assert(messages[messages.size()-2].find("size=0x2000 offset=0x100000012 flags=0x17")!=std::string::npos);
  assert(messages.back().find("tid=987654321")!=std::string::npos);
 }
 assert(ranges==2);
 expectedLevel=3;expectedFragment=4;expectedAddress=0x123456789000ULL;
 for(UInt64 encoded:{UInt64{0},~UInt64{0},UInt64{0x0600123456789067ULL},UInt64{1}<<63}) {
  expectedPTE=encoded;int old=logs;
  assert(X5000::traceGetPTEValue(object,expectedLevel,expectedAddress,expectedFlags,expectedFragment)==encoded);
  assert(logs==old+1 && std::memcmp(original,object,sizeof(object))==0);
 }
 assert(ptes==4);
 assert(GPUVMTraceData::interestingRange(0x3fffffff0ULL,32));
 assert(!GPUVMTraceData::interestingRange(0x400100000ULL,4096));
 assert(!GPUVMTraceData::interestingRange(0x400000000ULL,0));
 assert(!GPUVMTraceData::interestingRange(~UInt64{0}-8,32));
 for(auto outside:{UInt64{0x1000},UInt64{0x400100000},~UInt64{0}-8}) {
  expectedAddress=outside;expectedSize=32;int old=logs;
  assert(X5000::traceMapGPUVirtualRange(object,expectedAddress,expectedMemory,expectedOffset,expectedSize,expectedFlags)==nativeResult);
  assert(logs==old);
 }
 expectedAddress=0x400004000ULL;
 processName="WindowServer";int old=logs;
 assert(X5000::traceCommitGPUPageTable(object)==nativeResult && logs==old && commits==3);
 X5000::traceGetPTEValue(object,expectedLevel,expectedAddress,expectedFlags,expectedFragment);assert(logs==old);
 processName="gl_blend_probe";getMember<UInt64>(object,GPUVMTraceData::GPUAddressOffset)=0x1000;
 old=logs;assert(X5000::traceUpdateGPUPageTable(object)==nativeResult && logs==old && updates==3);
 getMember<UInt64>(object,GPUVMTraceData::GPUAddressOffset)=expectedAddress;
 for(unsigned i=0;i<GPUVMTraceData::MaximumEvents+5;i++)X5000::traceCommitGPUPageTable(object);
 old=logs;X5000::traceCommitGPUPageTable(object);assert(logs==old);
 assert(getMember<UInt32>(object,GPUVMTraceData::OptionsOffset)==0x12345678);
 expectedAddress=0x123456789000ULL;
 for(unsigned i=0;i<GPUVMTraceData::MaximumPTEEvents+5;i++)X5000::traceGetPTEValue(object,expectedLevel,expectedAddress,expectedFlags,expectedFragment);
 old=logs;X5000::traceGetPTEValue(object,expectedLevel,expectedAddress,expectedFlags,expectedFragment);assert(logs==old);
}
'''
with tempfile.TemporaryDirectory() as directory:
    d=Path(directory);(d/'libkern').mkdir()
    (d/'libkern/OSTypes.h').write_text('#include <cstdint>\n#include <cstddef>\nusing UInt8=uint8_t;using UInt32=uint32_t;using UInt64=uint64_t;\n')
    (d/'test.cpp').write_text(prefix+production+suffix)
    subprocess.run(['xcrun','clang++','-std=c++17','-O1','-fsanitize=address,undefined','-fno-omit-frame-pointer',
                    '-I'+str(d),'-I'+str(ROOT/'NootedRed'),str(d/'test.cpp'),'-o',str(d/'test')],check=True)
    subprocess.run([str(d/'test')],check=True)
# Compare the compiled diagnostic prefixes with this host's unmodified kernel-collection data.
from gen_vcn_kernel_data import KernelCollection,DEFAULT_KC,X5000_ID
if DEFAULT_KC.exists():
    k=KernelCollection(DEFAULT_KC).kexts[X5000_ID]
    if k.uuid.hex()=='41c43219294b3932b77e68824533e800':
        data=(ROOT/'NootedRed/GPUVMTraceData.hpp').read_text()
        methods=re.findall(r'\{"([^"]+)",\s*\{([^}]+)\}\}',data)
        assert len(methods)==5
        for name,hexes in methods:
            expected=bytes(int(x,16) for x in re.findall(r'0x([0-9A-Fa-f]{2})',hexes))
            assert len(expected)==32 and k.read(k.symbols[name],32)==expected,name
        print('24H32 native method prefixes match the installed kernel collection')
print('VM trace: opt-in/UUID/version/prefix/range guards; partial-route state; exact argument/result forwarding; read-only object access; process/address filter and log cap passed')
print('VM trace v2: five guarded methods, native range arguments and full 64-bit PTE returns preserved')
