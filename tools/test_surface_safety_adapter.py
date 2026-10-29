#!/usr/bin/env python3
"""Run actual private surface installer code against synthetic VM with fatal sanitizers."""
from pathlib import Path
import subprocess,tempfile
from test_media_safety_adapter import SDK
ROOT=Path(__file__).resolve().parents[1]
SOURCE=r'''
#include "sdk.hpp"
#include <SurfaceExactPlan.hpp>
#include <SurfaceSafetyPolicy.hpp>
static std::map<std::string,unsigned> properties;
#include "user-cache-dynamic.hpp"
bool failKernel=false;unsigned kernelLive=0;
static unsigned protectCalls=0,failProtectAt=0,queryCalls=0,writeCalls=0,corruptWriteAt=0,queryMode=0;
static bool persistentRestoreFailure=false,mutateOnQuery=false;
static std::map<UInt64,int> maximums;
void recordProp(const char* k,UInt32 v){properties[k]=v;}
void proc_name(int,char* out,int size){snprintf(out,size,"WindowServer");}
int vm_protect(vm_map_t,UInt64 a,size_t,int maximum,int protection){
 ++protectCalls;if(protectCalls==failProtectAt)return 1;
 if(!protections.count(a)||maximum)return 1;
 if(persistentRestoreFailure&&protection==5)return 1;
 if((protection&7)&~maximums[a])return 1;
 protections[a]=protection&7;return 0;
}
static int query(vm_map_t,UInt64* address,UInt64* size,unsigned*,int* info,unsigned* count){
 ++queryCalls;
 if(mutateOnQuery){mutateOnQuery=false;blocks.at(imageAddresses[0])[UserSurface24H232Data::ResolverFunctions[2].rva+200]^=0x80;}
 auto it=protections.find(*address);if(it==protections.end())return 1;*size=4096;*count=3;
 auto*out=reinterpret_cast<vm_region_submap_short_info_data_64_t*>(info);out->protection=it->second;out->max_protection=maximums.at(*address);out->is_submap=0;
 if(queryMode==1)return 1;if(queryMode==2)*count=2;if(queryMode==3)*size=4095;
 if(queryMode==4)*address+=4096;if(queryMode==5)out->is_submap=1;
 return 0;
}
static int copyIn(const void*a,void*b,size_t n){return reader(reinterpret_cast<UInt64>(a),b,n);}
static int copyOut(const void*a,void*b,size_t n){auto addr=reinterpret_cast<UInt64>(b);++writeCalls;
 int result=writer(a,addr,n);
 if(writeCalls==corruptWriteAt){UInt8 v;assert(!reader(addr,&v,1));v^=0x80;put(addr,&v,1);}
 return result;
}
#include "ACTUAL_CPP"
namespace Data=UserSurface24H232Data;
static SurfaceExactPlan::Workspace reference;
static void setup(bool blendAlready=false){
 cache(Data::ResolverImages,Data::ResolverFunctions,false,nullptr,0,true);put(base+88,Data::CacheUUID,16);
 float value=3;put(imageAddresses[0]+0x38a048,&value,4);put(imageAddresses[0]+0x51829,Data::NativeDump,sizeof(Data::NativeDump));
 UserSharedCache::Input input{reader,{}};assert(SurfaceExactPlan::build(input,base,0x1636,true,reference));
 pages(reference.resolved,4);
 if(blendAlready)put(base+reference.resolved[2].offset,reference.resolved[2].patched,2);
 maximums.clear();for(auto& item:protections)maximums[item.first]=7;
 failKernel=persistentRestoreFailure=mutateOnQuery=false;protectCalls=failProtectAt=queryCalls=writeCalls=corruptWriteAt=queryMode=0;
 assert(kernelLive==0);SurfaceSafety::halted=0;SurfaceSafety::published=0;
 assert(SurfaceSafety::configure(copyIn,copyOut,query));
}
static auto run(bool blend=true){auto result=SurfaceSafety::install((void*)1,base,0x1636,blend,99);assert(!kernelLive);return result;}
int main(){using Result=SurfaceSafety::Result;unsigned cases=0;
 for(unsigned device=0;device<65536;++device){
  assert(SurfaceSafetyPolicy::eligible(true,"24H232",24,device)==bool(Data::findDevice(device)));++cases;
 }
 for(bool requested:{false,true})for(const char* build:{"24H232","24H32","","24H232x"})for(unsigned major:{23U,24U,25U}){
  assert(SurfaceSafetyPolicy::eligible(requested,build,major,0x1636)==(requested&&major==24&&!strcmp(build,"24H232")));++cases;
 }
 setup();auto stock=blocks;assert(run()==Result::Installed&&writeCalls==4);rx();
 auto installed=blocks;auto baselineWrites=writeCalls,baselineProtects=protectCalls;
 assert(properties["NRedSurfaceFixRevision"]==1&&properties["NRedSurfaceFixWindowServerPID"]==99);
 assert(run()==Result::Installed&&blocks==installed&&writeCalls==baselineWrites);cases+=2;
 for(unsigned fail=1;fail<=baselineWrites;++fail){setup();stock=blocks;failWrite=fail;
  assert(run()==Result::Rejected&&blocks==stock&&!SurfaceSafety::halted);rx();++cases;}
 for(unsigned corrupt=1;corrupt<=baselineWrites;++corrupt){setup();stock=blocks;corruptWriteAt=corrupt;
  assert(run()==Result::Rejected&&blocks==stock&&!SurfaceSafety::halted);rx();++cases;}
 for(unsigned fail=1;fail<=baselineProtects;++fail){setup();stock=blocks;failProtectAt=fail;auto result=run();
  assert(result==Result::Installed||result==Result::Rejected);
  assert(blocks==(result==Result::Installed?installed:stock)&&!SurfaceSafety::halted);rx();++cases;}
 // Existing blend is checked but receives neither another write nor COW.
 setup(true);const auto gatePage=(base+reference.resolved[2].offset)&~UInt64(4095);
 assert(run()==Result::Installed&&writeCalls==3&&protectCalls==baselineProtects-2);rx();++cases;
 // Disabling local blend preserves its stock native branch.
 setup();UInt8 gate[2];assert(!reader(base+reference.resolved[2].offset,gate,2));
 assert(run(false)==Result::Installed&&writeCalls==3);UInt8 seen[2];assert(!reader(base+reference.resolved[2].offset,seen,2));
 assert(!memcmp(gate,seen,2)&&protections.at(gatePage)==5);rx();++cases;
 setup();stock=blocks;failKernel=true;assert(run()==Result::Rejected&&blocks==stock&&!writeCalls&&!protectCalls);++cases;
 setup();stock=blocks;word32(base+88,0);auto wrong=blocks;assert(run()==Result::Rejected&&blocks==wrong&&!writeCalls&&!protectCalls);++cases;
 setup();stock=blocks;mutateOnQuery=true;assert(run()==Result::Rejected&&!writeCalls&&!protectCalls);
 stock.at(imageAddresses[0])[Data::ResolverFunctions[2].rva+200]^=0x80;assert(blocks==stock);++cases;
 setup();failWrite=4;corruptWriteAt=5;assert(run()==Result::Halted&&SurfaceSafety::halted);
 auto damaged=blocks;auto writesBefore=writeCalls;assert(run()==Result::Halted&&blocks==damaged&&writeCalls==writesBefore);cases+=2;
 setup();persistentRestoreFailure=true;assert(run()==Result::Halted&&SurfaceSafety::halted);++cases;
 setup();stock=blocks;protections.begin()->second=3;assert(run()==Result::Rejected&&blocks==stock&&!writeCalls);++cases;
 setup();stock=blocks;maximums.begin()->second=1;assert(run()==Result::Rejected&&blocks==stock&&!writeCalls);++cases;
 // An incomplete prior installation is never completed opportunistically.
 setup();put(base+reference.resolved[0].offset,reference.resolved[0].patched,reference.resolved[0].size);auto mixed=blocks;
 assert(run()==Result::Rejected&&blocks==mixed&&!writeCalls&&!protectCalls);++cases;
 for(unsigned mode=1;mode<=5;++mode){setup();stock=blocks;queryMode=mode;
  assert(run()==Result::Rejected&&blocks==stock&&!writeCalls&&!protectCalls);++cases;}
 printf("PASS %u actual surface adapter cases: four-site install/repeat, every write/protect failure, blend ownership, precommit function mutation, allocation, UUID, mixed states, permissions and rollback halt\n",cases);
}
'''
def main():
 with tempfile.TemporaryDirectory(prefix='nred-surface-adapter-') as directory:
  p=Path(directory)
  for folder in ['IOKit','libkern','mach','sys']:(p/folder).mkdir()
  (p/'sdk.hpp').write_text(SDK)
  for name in ['IOKit/IOTypes.h','IOKit/IOLib.h','libkern/OSTypes.h','libkern/OSAtomic.h','mach/vm_map.h','mach/vm_region.h','sys/proc.h']:(p/name).write_text('#pragma once\n#include "sdk.hpp"\n')
  (p/'NRed.hpp').write_text('#pragma once\n#include "sdk.hpp"\nstruct NRed{static NRed& singleton(){static NRed n;return n;}void setProp32(const char*k,UInt32 v){recordProp(k,v);}};\n')
  (p/'test.cpp').write_text(SOURCE.replace('ACTUAL_CPP',str(ROOT/'NootedRed/SurfaceSafety.cpp')))
  subprocess.run(['xcrun','clang++','-std=c++23','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(p),'-I'+str(ROOT/'NootedRed'),'-I'+str(ROOT/'tools/fixtures'),str(p/'test.cpp'),'-o',str(p/'test')],check=True,timeout=90)
  subprocess.run([str(p/'test')],check=True,timeout=120)
if __name__=='__main__':main()
