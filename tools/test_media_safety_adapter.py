#!/usr/bin/env python3
"""Execute the actual private media adapter against synthetic VM and real code references."""
from pathlib import Path
import subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
SDK=r'''
#pragma once
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <map>
#include <vector>
#include <string>
#include <set>
#include <cstdio>
#include <cassert>
using UInt8=uint8_t;using UInt32=uint32_t;using UInt64=uint64_t;
using vm_map_t=void*;using vm_address_t=UInt64;using mach_vm_address_t=UInt64;using mach_vm_size_t=UInt64;
using vm_prot_t=int;using kern_return_t=int;using natural_t=unsigned;using mach_msg_type_number_t=unsigned;using vm_region_recurse_info_t=int*;
struct vm_region_submap_short_info_data_64_t{int protection,max_protection;unsigned is_submap;};
constexpr unsigned VM_REGION_SUBMAP_SHORT_INFO_COUNT_64=3;
constexpr int KERN_SUCCESS=0,VM_FLAGS_ANYWHERE=1,FALSE=0,TRUE=1,VM_PROT_READ=1,VM_PROT_WRITE=2,VM_PROT_EXECUTE=4,VM_PROT_COPY=8;
int vm_allocate(vm_map_t,vm_address_t*,size_t,int);int vm_deallocate(vm_map_t,vm_address_t,size_t);int vm_protect(vm_map_t,UInt64,size_t,int,int);
void proc_name(int,char*,int);void recordProp(const char*,UInt32);
inline bool OSCompareAndSwap(UInt32 before,UInt32 after,volatile UInt32* p){return __sync_bool_compare_and_swap(p,before,after);}
inline UInt32 OSIncrementAtomic(volatile UInt32*p){return __sync_fetch_and_add(p,1);}
extern bool failKernel;extern unsigned kernelLive;
inline void* allocateKernel(size_t n){if(failKernel)return nullptr;++kernelLive;return calloc(1,n);}
inline void freeKernel(void*p){if(p){assert(kernelLive);--kernelLive;free(p);}}
#define IONewZero(T,n) static_cast<T*>(allocateKernel(sizeof(T)*(n)))
#define IODelete(p,T,n) freeKernel(p)
'''
SOURCE=r'''
#include "sdk.hpp"
#include <UserVideoGuardResolver.hpp>
#include <MediaReference24H232.hpp>
#include <MediaSafetyPolicy.hpp>
static std::map<std::string,unsigned> properties;
#include "user-cache-dynamic.hpp"
bool failKernel=false;unsigned kernelLive=0;
static bool failAllocation=false,ignoreMaximum=false,persistentRestoreFailure=false,corruptPayload=false,mutateMedia=false;
static UInt64 payload=0x40000000;static unsigned allocations=0,deallocations=0,protectCalls=0,failProtectAt=0,writeCalls=0,corruptWriteAt=0;
static std::map<UInt64,int> maximums;
void recordProp(const char* k,UInt32 v){properties[k]=v;}
void proc_name(int,char* out,int size){snprintf(out,size,"VTEncoderXPCService");}
int vm_allocate(vm_map_t,vm_address_t* a,size_t,int){if(failAllocation)return 1;assert(!blocks.count(payload));*a=payload;blocks[payload].resize(4096);protections[payload]=3;maximums[payload]=7;++allocations;
 if(mutateMedia)blocks[base+MediaReference24H232::Pages[0].offset][4095]^=0x80;
 return 0;}
int vm_deallocate(vm_map_t,vm_address_t a,size_t){assert(a==payload);assert(blocks.erase(a)==1);protections.erase(a);maximums.erase(a);++deallocations;return 0;}
int vm_protect(vm_map_t,UInt64 a,size_t,int maximum,int protection){
 ++protectCalls;if(protectCalls==failProtectAt)return 1;
 if(!protections.count(a))return 1;
 if(persistentRestoreFailure&&a!=payload&&protection==5)return 1;
 if(maximum){if(!ignoreMaximum){maximums[a]=protection&7;protections[a]&=protection&7;}return 0;}
 if((protection&7)&~maximums[a])return 1;
 protections[a]=protection&7;return 0;
}
static int query(vm_map_t,UInt64* address,UInt64* size,unsigned*,int* info,unsigned* count){
 auto it=protections.find(*address);if(it==protections.end())return 1;*size=4096;*count=3;
 auto*out=reinterpret_cast<vm_region_submap_short_info_data_64_t*>(info);out->protection=it->second;out->max_protection=maximums.at(*address);out->is_submap=0;return 0;
}
static int copyIn(const void*a,void*b,size_t n){return reader(reinterpret_cast<UInt64>(a),b,n);}
static int copyOut(const void*a,void*b,size_t n){auto addr=reinterpret_cast<UInt64>(b);++writeCalls;
 int result=writer(a,addr,n);
 if(writeCalls==corruptWriteAt|| (corruptPayload&&addr==payload)){UInt8 v;assert(reader(addr,&v,1)==0);v^=0x80;put(addr,&v,1);}
 return result;
}
#include "ACTUAL_CPP"
static void setup(){
 using namespace UserVideoGuard24Data;
 cache(ResolverImages,ResolverFunctions,true,SectionTargets,sizeof(SectionTargets)/sizeof(SectionTargets[0]));
 const UInt8 uuid[]={0x90,0xdb,0x0d,0xeb,0x23,0x44,0x36,0x01,0xb0,0x11,0xb8,0x73,0x12,0xd7,0x4c,0xfb};put(base+88,uuid,16);
 for(auto& p:MediaReference24H232::Pages){blocks[base+p.offset]={p.bytes,p.bytes+4096};protections[base+p.offset]=5;}
 UserSharedCache::Input in{reader,{}};UserVideoGuardResolver::Plan guard;assert(UserVideoGuardResolver::resolve(in,base,24,guard));pages(guard.patches,guard.count);
 maximums.clear();for(auto& item:protections)maximums[item.first]=7;
 failKernel=failAllocation=ignoreMaximum=persistentRestoreFailure=corruptPayload=mutateMedia=false;
 allocations=deallocations=protectCalls=failProtectAt=writeCalls=corruptWriteAt=0;assert(kernelLive==0);
 MediaSafety::halted=0;MediaSafety::published=0;
 assert(MediaSafety::configure(copyIn,copyOut,query));
}
static void run(){MediaSafety::install((void*)1,base,99);assert(kernelLive==0);}
int main(){unsigned cases=0;
 const char* builds[]={nullptr,"","24H32","24H232","24H233"};
 for(bool requested:{false,true})for(const char* build:builds)
  for(unsigned major:{23U,24U,25U})for(unsigned device:{0U,0x15e7U,0x1636U,0x1638U,0x164cU,0x164eU}){
   const bool expected=requested&&build&&strcmp(build,"24H232")==0&&major==24
    &&(device==0x15e7||device==0x1636||device==0x1638||device==0x164c);
   assert(MediaSafetyPolicy::eligible(requested,build,major,device)==expected);++cases;
  }
 setup();auto stock=blocks;run();assert(properties["NRedVCNSafetyInstalled"]>0&&properties["NRedVCNGuardedEncoderPID"]==99&&allocations==1&&!deallocations);rx();
 auto installed=blocks;auto baselineWrites=writeCalls;auto baselineProtects=protectCalls;
 assert(baselineWrites==19);run();assert(blocks==installed&&writeCalls==baselineWrites&&allocations==1);cases+=2;
 for(unsigned failure=1;failure<=baselineWrites;++failure){setup();stock=blocks;failWrite=failure;run();assert(blocks==stock&&allocations==deallocations&&!MediaSafety::halted);rx();++cases;}
 for(unsigned failure=1;failure<=baselineProtects;++failure){setup();stock=blocks;failProtectAt=failure;run();
  if(properties.count("NRedVCNSafetyInstalled")){assert(allocations==1&&!deallocations);}
  else assert(blocks==stock&&allocations==deallocations);
  rx();assert(!MediaSafety::halted);++cases;
 }
 for(unsigned failure=0;failure<4;++failure){setup();stock=blocks;
  if(failure==0)failKernel=true;if(failure==1)failAllocation=true;if(failure==2)ignoreMaximum=true;if(failure==3)corruptPayload=true;
  run();assert(blocks==stock&&allocations==deallocations&&!MediaSafety::halted);rx();++cases;
 }
 // A silent media rollback corruption must retain the already-published guard entries/page.
 setup();failWrite=6;corruptWriteAt=7;run();assert(MediaSafety::halted&&allocations==1&&!deallocations&&blocks.count(payload));
 auto failed=blocks;auto calls=writeCalls;run();assert(blocks==failed&&writeCalls==calls);cases+=2;
 setup();persistentRestoreFailure=true;run();assert(MediaSafety::halted&&allocations==1&&!deallocations);++cases;
 // Cache identity is required before allocating work or touching any entry.
 setup();stock=blocks;word32(base+88,0);auto wrong=blocks;run();assert(blocks==wrong&&!allocations&&!writeCalls);++cases;
 setup();stock=blocks;blocks[base+MediaReference24H232::Pages[9].offset][0]^=1;auto bad=blocks;
 run();assert(blocks==bad&&!allocations&&!writeCalls);++cases;
 setup();stock=blocks;mutateMedia=true;run();
 stock[base+MediaReference24H232::Pages[0].offset][4095]^=0x80;
 assert(blocks==stock&&allocations==deallocations&&writeCalls==1&&!MediaSafety::halted);rx();++cases;
 printf("PASS %u actual private adapter cases: ordered 18-site commit, repeat verification, every write/protect failure, kernel/user allocation, RX maximum, payload corruption, rollback retention and halt\n",cases);
}
'''
def main():
 with tempfile.TemporaryDirectory(prefix='nred-media-adapter-') as d:
  p=Path(d)
  for folder in ['IOKit','libkern','mach','sys']:(p/folder).mkdir()
  (p/'sdk.hpp').write_text(SDK)
  for name in ['IOKit/IOTypes.h','IOKit/IOLib.h','libkern/OSTypes.h','libkern/OSAtomic.h','mach/vm_map.h','mach/vm_region.h','sys/proc.h']:(p/name).write_text('#pragma once\n#include "sdk.hpp"\n')
  (p/'NRed.hpp').write_text('#pragma once\n#include "sdk.hpp"\nstruct NRed{static NRed& singleton(){static NRed n;return n;}void setProp32(const char*k,UInt32 v){recordProp(k,v);}};\n')
  (p/'UserPatches.hpp').write_text('#pragma once\n#include "sdk.hpp"\nnamespace UserPatcher{enum class FileSegment{SegmentTextText};}\nstruct UserPatches{struct PagePatch{UserPatcher::FileSegment segment;const UInt8*page;const UInt8*find;const UInt8*replace;size_t size,skip,count;bool glDriver=false,exactOnly=false;};};\n')
  (p/'test.cpp').write_text(SOURCE.replace('ACTUAL_CPP',str(ROOT/'NootedRed/MediaSafety.cpp')))
  subprocess.run(['xcrun','clang++','-std=c++23','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(p),'-I'+str(ROOT/'NootedRed'),'-I'+str(ROOT/'tools/fixtures'),str(p/'test.cpp'),'-o',str(p/'test')],check=True,timeout=90)
  subprocess.run([str(p/'test')],check=True,timeout=90)
if __name__=='__main__':main()
