#!/usr/bin/env python3
"""Execute real cache patch planners/installers with simulated user memory; no GPU access."""
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from test_gl_semantic_data import load_arrays
from test_patch_dispatch import method

ROOT = Path(__file__).resolve().parents[1]
SHIM = r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <map>
#include <vector>
#include <string>
#include <cstdio>
#include <UserCodePatch.hpp>
#include <UserSharedCacheData.hpp>
#include <UserSubmitGuard.hpp>
using mach_vm_address_t=uint64_t; using mach_vm_offset_t=uint64_t;
using vm_address_t=uint64_t; using vm_map_t=void*; using proc_t=void*;
constexpr unsigned PAGE_SIZE=4096;
constexpr int KERN_SUCCESS=0, VM_FLAGS_ANYWHERE=1, FALSE=0, TRUE=1;
constexpr int VM_PROT_NONE=0, VM_PROT_READ=1, VM_PROT_WRITE=2, VM_PROT_EXECUTE=4, VM_PROT_COPY=8;
using vm_prot_t=int;
#define DBGLOG(...) do {} while (0)
struct Version { unsigned value=24; unsigned major() const { return value; } };
Version version;
Version currentKernelVersion() { return version; }
struct NRed {
    std::map<std::string,unsigned> props;
    static NRed& singleton() { static NRed n; return n; }
    void setProp32(const char* name, unsigned value) { props[name]=value; }
};
int current_task() { return 1; }
proc_t current_proc() { return reinterpret_cast<void*>(1); }
int proc_pid(proc_t) { return 1; }
void proc_name(int, char* name, int size) { std::snprintf(name,size,"WindowServer"); }
int OSIncrementAtomic(volatile unsigned* value) { return ++*value; }
namespace Buffer {
 template<class T> T* create(size_t size) { return static_cast<T*>(std::malloc(sizeof(T)*size)); }
 template<class T> void deleter(T* p) { std::free(p); }
}
struct Region { std::vector<UInt8> bytes=std::vector<UInt8>(4096); int protection=5, maximum=7; };
std::map<UInt64,Region> regions;
UInt64 methodAddress=0, nextAllocation=0x100000000ULL;
int allocations=0, deallocations=0;
bool partialEntry=false, rollbackFails=false, corruptPayload=false, failRestoreOnce=false;
bool failMaximum=false, ignoreMaximum=false;
int copyIn(const void* source, void* data, size_t size) {
    UInt64 address=reinterpret_cast<UInt64>(source), page=address & ~4095ULL;
    auto i=regions.find(page);
    if(i==regions.end() || (address-page)+size>4096) return 1;
    std::memcpy(data,i->second.bytes.data()+(address-page),size); return 0;
}
int copyOut(const void* data, void* destination, size_t size) {
    UInt64 address=reinterpret_cast<UInt64>(destination), page=address & ~4095ULL;
    auto i=regions.find(page);
    if(i==regions.end() || !(i->second.protection & 2)) return 1;
    if(address==methodAddress && partialEntry) {
        partialEntry=false; std::memcpy(i->second.bytes.data()+(address-page),data,7); return 1;
    }
    if(address==methodAddress && rollbackFails) return 1;
    std::memcpy(i->second.bytes.data()+(address-page),data,size);
    if(corruptPayload && page>=0x100000000ULL && page<0x200000000ULL) i->second.bytes[0]^=1;
    return 0;
}
int (*copyInFunc)(const void*,void*,size_t)=copyIn;
int (*copyOutFunc)(const void*,void*,size_t)=copyOut;
vm_map_t getMap(int) { return reinterpret_cast<void*>(1); }
vm_map_t (*getTaskMapFunc)(int)=getMap;
bool leafProtection(vm_map_t, UInt64 address, int& protection, int* maximum=nullptr) {
 auto i=regions.find(address & ~4095ULL); if(i==regions.end()) return false;
 protection=i->second.protection;
 if(maximum) *maximum=i->second.maximum;
 return true;
}
int vm_protect(vm_map_t, UInt64 page, size_t, int maximum, int protection) {
 auto i=regions.find(page); if(i==regions.end()) return 1;
 if(maximum) {
   // Seal only an unpublished payload; existing cache pages need rollback rights.
   assert(page>=0x100000000ULL && page<0x200000000ULL);
   if(failMaximum) return 1;
   if(!ignoreMaximum) { i->second.maximum=protection & 7; i->second.protection&=protection & 7; }
   return 0;
 }
 if(page==(methodAddress & ~4095ULL) && protection==5 && failRestoreOnce) {
   failRestoreOnce=false; return 1;
 }
 if((protection & 7) & ~i->second.maximum) return 1;
 i->second.protection=protection & 7; return 0;
}
int vm_allocate(vm_map_t,UInt64* address,size_t,int) {
 *address=nextAllocation; nextAllocation+=4096; regions[*address]=Region{};
 regions[*address].protection=3; ++allocations; return 0;
}
int vm_deallocate(vm_map_t,UInt64 address,size_t) { regions.erase(address); ++deallocations; return 0; }
struct SharedRegionCheckArgs { UInt64 startAddress; };
class UserPatches {
 public:
    static UserPatches& singleton() { static UserPatches value; return value; }
    bool submitGuardEnabled=true, legacyBlendEnabled=true;
    UInt64 orgSharedRegionCheck=0;
    static int wrapSharedRegionCheck(proc_t,void*,int*);
    void applySubmitGuard(proc_t,void*); void applyLegacyBlend(vm_map_t,mach_vm_offset_t,proc_t);
};
'''
CASES = r'''
#define FunctionCast(name, pointer) reinterpret_cast<decltype(&name)>(pointer)
using task_t=void*;
struct Entitlement { int releases=0; void release() { ++releases; } };
Entitlement trueEntitlement, falseEntitlement;
Entitlement* kOSBooleanTrue=&trueEntitlement;
Entitlement* returnedEntitlement=nullptr;
struct IOUserClient { static Entitlement* copyClientEntitlement(task_t,const char* key) {
 assert(!std::strcmp(key,"com.apple.private.fpsd.client")); return returnedEntitlement;
} };
__FAIRPLAY_BODY__
__WRAPPER_BODY__
int syscallResult=0;
void* expectedArgs=nullptr; int* expectedReturn=nullptr;
int originalSyscall(proc_t process,void* args,int* result) {
 assert(process==current_proc() && args==expectedArgs && result==expectedReturn);
 assert(allocations==0); // Patch work must not run before the native syscall returns.
 *result=37; return syscallResult;
}
constexpr UInt64 base=0x7FF800000000ULL;
void reset() {
 regions.clear(); allocations=deallocations=0; partialEntry=rollbackFails=corruptPayload=failRestoreOnce=false;
 failMaximum=ignoreMaximum=false;
 NRed::singleton().props.clear(); version.value=24;
 Region header; std::memcpy(header.bytes.data(),UserSharedCacheData::magic,16);
 std::memcpy(header.bytes.data()+88,UserSharedCacheData::sequoia,16); regions[base]=header;
 methodAddress=base+UserSubmitGuardData::kMethodOffsetSequoia;
 Region entry; std::memcpy(entry.bytes.data()+(methodAddress&4095),UserSubmitGuardData::MethodOriginal,15);
 regions[methodAddress & ~4095ULL]=entry;
 Region metal; std::memcpy(metal.bytes.data(),kMTLControlPage_Sequoia,4096);
 regions[base+0x3087B3000ULL]=metal;
}
bool originalEntry() {
 UInt8 data[15]; return copyIn(reinterpret_cast<void*>(methodAddress),data,15)==0
  && std::memcmp(data,UserSubmitGuardData::MethodOriginal,15)==0;
}
int main() {
 UInt8 target[4096], changed[4096]; UInt64 offset; size_t first,size;
 for(unsigned major : {22,23,24,25}) {
  const auto* ref=major==22?kMTLControlPage_Ventura:major==23?kMTLControlPage_Sonoma:major==24?kMTLControlPage_Sequoia:kMTLControlPage_Tahoe;
  assert(legacyBlendPlan(major,ref,target,offset,first,size));
  assert(size<=128 && target[first]==0xeb);
  if(major!=25) {
   assert(size==2);
   size_t allow=major==22?0x258:major==23?0x1e1:0x198;
   assert(!std::memcmp(target+allow,ref+allow,3));
   for(size_t i=0;i<4096;i++) assert(i==first || target[i]==ref[i]);
  }
  std::memcpy(changed,target,4096);
  assert(legacyBlendPlan(major,changed,target,offset,first,size)); // Idempotent full-page match.
  changed[0]^=1; assert(!legacyBlendPlan(major,changed,target,offset,first,size));
  std::memcpy(changed,ref,4096); changed[first]=0x90;
  assert(!legacyBlendPlan(major,changed,target,offset,first,size));
 }
 assert(!legacyBlendPlan(26,kMTLControlPage_Sequoia,target,offset,first,size));
 for(unsigned major : {22,23,24,25}) {
  UInt8 header[104]{}; std::memcpy(header,UserSharedCacheData::magic,16);
  const auto* uuid=major==22?UserSharedCacheData::ventura:major==23?UserSharedCacheData::sonoma:major==24?UserSharedCacheData::sequoia:UserSharedCacheData::tahoe;
  std::memcpy(header+88,uuid,16); assert(UserSharedCacheData::matches(major,header));
  header[88]^=1; assert(!UserSharedCacheData::matches(major,header));
 }
 UserPatches patches; SharedRegionCheckArgs args{0};
 reset(); patches.applySubmitGuard(current_proc(),&args);
 assert(allocations==1 && deallocations==0 && !originalEntry());
 assert(NRed::singleton().props["NRedSubmitGuardWindowServerApplied"]==1);
 assert(NRed::singleton().props["NRedLegacyBlendWindowServerApplied"]==1);
 auto blendObservations=NRed::singleton().props["NRedLegacyBlendApplied"];
 patches.applySubmitGuard(current_proc(),&args); assert(allocations==1);
 assert(NRed::singleton().props["NRedLegacyBlendApplied"]>blendObservations);
 UInt64 destination=0; copyIn(reinterpret_cast<void*>(methodAddress+6),&destination,8);
 assert(regions[destination].protection==5 && regions[destination].maximum==5);
 regions[destination].maximum=7;
 patches.applySubmitGuard(current_proc(),&args);
 assert(NRed::singleton().props["NRedSubmitGuardRejected"]==2 && allocations==1);
 regions[destination].maximum=5;
 regions[destination].bytes[0]^=1;
 patches.applySubmitGuard(current_proc(),&args);
 assert(NRed::singleton().props["NRedSubmitGuardRejected"]==2 && allocations==1);

 reset(); regions[base].bytes[88]^=1; patches.applySubmitGuard(current_proc(),&args);
 assert(allocations==0 && originalEntry());
 reset(); corruptPayload=true; patches.applySubmitGuard(current_proc(),&args);
 assert(allocations==1 && deallocations==1 && originalEntry());
 reset(); failMaximum=true; patches.applySubmitGuard(current_proc(),&args);
 assert(allocations==1 && deallocations==1 && originalEntry());
 reset(); ignoreMaximum=true; patches.applySubmitGuard(current_proc(),&args);
 assert(allocations==1 && deallocations==1 && originalEntry());
 reset(); partialEntry=true; patches.applySubmitGuard(current_proc(),&args);
 assert(allocations==1 && deallocations==1 && originalEntry());
 assert(regions[methodAddress&~4095ULL].protection==5);
 reset(); failRestoreOnce=true; patches.applySubmitGuard(current_proc(),&args);
 assert(allocations==1 && deallocations==1 && originalEntry());
 reset(); partialEntry=rollbackFails=true; patches.applySubmitGuard(current_proc(),&args);
 assert(allocations==1 && deallocations==0 && !originalEntry());
 assert(NRed::singleton().props["NRedSubmitGuardRejected"]==4);
 auto& hooked=UserPatches::singleton();
 hooked.orgSharedRegionCheck=reinterpret_cast<UInt64>(&originalSyscall);
 for(bool enabled : {false,true}) for(bool blend : {false,true}) for(int syscallStatus : {0,5}) {
  reset(); int result=0; syscallResult=syscallStatus; expectedArgs=&args; expectedReturn=&result;
  hooked.submitGuardEnabled=enabled;hooked.legacyBlendEnabled=blend;
  assert(UserPatches::wrapSharedRegionCheck(current_proc(),&args,&result)==syscallStatus);
  assert(result==37 && allocations==(enabled && syscallStatus==0 ? 1:0));
  assert((NRed::singleton().props["NRedLegacyBlendApplied"]>0)==(blend && syscallStatus==0));
 }
 assert(!isFairPlayClient(nullptr)); returnedEntitlement=nullptr;
 assert(!isFairPlayClient(current_proc())); returnedEntitlement=&falseEntitlement;
 assert(!isFairPlayClient(current_proc()) && falseEntitlement.releases==1);
 returnedEntitlement=&trueEntitlement;
 assert(isFairPlayClient(current_proc()) && trueEntitlement.releases==1);
 std::puts("production cache patches: page plans, syscall ordering, UUID rejection, idempotency, sealed payload permissions, permission failure/readback rejection, partial-write rollback and retained reachable payload passed");
}
'''

def main():
    source = (ROOT / 'NootedRed/UserPatches.cpp').read_text()
    arrays = load_arrays(ROOT / 'NootedRed/UserPatches.cpp')
    names = ['kMTLControlPage_Ventura','kMTLControlPage_Sonoma','kMTLControlPage_Sequoia','kMTLControlPage_Tahoe',
             'kTahoeMTLAllowFind','kTahoeMTLAllowReplace']
    fixtures = '\n'.join('const UInt8 '+name+'[] = {'+','.join(map(str,arrays[name]))+'};' for name in names)
    backend = method(source,'struct UserCodeMemory\n')+';'
    planner = method(source,'bool legacyBlendPlan(')
    helpers = '\n'.join(method(source,name) for name in ('__attribute__((noinline)) bool userBytesEqual(', '__attribute__((noinline)) bool validSubmitGuardEntry('))
    bodies = '\n'.join(method(source,name) for name in (
        '__attribute__((noinline)) void UserPatches::applySubmitGuard(',
        '__attribute__((noinline)) void UserPatches::applyLegacyBlend('))
    with tempfile.TemporaryDirectory(prefix='nred-user-cache-') as directory:
        path = Path(directory)
        (path/'IOKit').mkdir(); (path/'libkern').mkdir()
        (path/'mach').mkdir()
        (path/'IOKit/IOTypes.h').write_text('#pragma once\n#include <cstdint>\nusing UInt8=uint8_t; using UInt32=uint32_t; using UInt64=uint64_t;\n')
        (path/'libkern/libkern.h').write_text('#pragma once\n#include <cstring>\n')
        (path/'mach/mach_types.h').write_text('#pragma once\n')
        (path/'test.cpp').write_text(SHIM+fixtures+backend+helpers+planner+bodies+CASES.replace(
            '__FAIRPLAY_BODY__',method(source,'bool isFairPlayClient(')).replace(
            '__WRAPPER_BODY__',method(source,'__attribute__((noinline)) int UserPatches::wrapSharedRegionCheck(')))
        subprocess.run(shlex.split(os.environ.get('CXX','c++'))+['-std=c++17','-O2','-Wall','-Wextra',
                         '-I'+str(path),'-I'+str(ROOT/'NootedRed'),str(path/'test.cpp'),'-o',str(path/'test')],check=True)
        subprocess.run([str(path/'test')],check=True)
        if sys.platform == 'darwin':
            # Check real Mach behavior in this test process only; no kext/GPU work.
            (path/'permissions.cpp').write_text(r'''
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <cassert>
#include <cstdio>
int main() {
 mach_vm_address_t page=0;
 auto task=mach_task_self();
 assert(mach_vm_allocate(task,&page,vm_page_size,VM_FLAGS_ANYWHERE)==KERN_SUCCESS);
 constexpr auto rx=VM_PROT_READ|VM_PROT_EXECUTE;
 assert(mach_vm_protect(task,page,vm_page_size,FALSE,rx)==KERN_SUCCESS);
 assert(mach_vm_protect(task,page,vm_page_size,TRUE,rx)==KERN_SUCCESS);
 mach_vm_address_t address=page;mach_vm_size_t size=0;natural_t depth=0;
 vm_region_submap_short_info_data_64_t info{};
 mach_msg_type_number_t count=VM_REGION_SUBMAP_SHORT_INFO_COUNT_64;
 assert(mach_vm_region_recurse(task,&address,&size,&depth,
   reinterpret_cast<vm_region_recurse_info_t>(&info),&count)==KERN_SUCCESS);
 assert(address==page&&size>=vm_page_size&&!info.is_submap);
 assert(info.protection==rx&&info.max_protection==rx);
 assert(mach_vm_protect(task,page,vm_page_size,FALSE,VM_PROT_READ|VM_PROT_WRITE)!=KERN_SUCCESS);
 assert(mach_vm_deallocate(task,page,vm_page_size)==KERN_SUCCESS);
 puts("native Mach payload sealing: current/maximum RX verified; ordinary write permission denied");
}
''')
            subprocess.run(['xcrun','clang++','-std=c++17',str(path/'permissions.cpp'),
                            '-o',str(path/'permissions')],check=True)
            subprocess.run([str(path/'permissions')],check=True)

if __name__ == '__main__':
    main()
