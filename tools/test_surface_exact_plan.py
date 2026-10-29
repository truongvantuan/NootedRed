#!/usr/bin/env python3
"""Exercise the actual exact-build SRD/scratch planner and mixed-state ownership rules."""
from pathlib import Path
import subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
SOURCE=r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <map>
#include <vector>
#include <set>
#include <string>
#include <SurfaceExactPlan.hpp>
static std::map<std::string,unsigned> properties;
#include "user-cache-dynamic.hpp"
namespace Data=UserSurface24H232Data;
static void setup(){
 cache(Data::ResolverImages,Data::ResolverFunctions,false,nullptr,0,true);put(base+88,Data::CacheUUID,16);
 float value=3;put(imageAddresses[0]+0x38a048,&value,4);
 put(imageAddresses[0]+0x51829,Data::NativeDump,sizeof(Data::NativeDump));
}
static bool build(UInt32 device,bool blend,SurfaceExactPlan::Workspace& p){
 UserSharedCache::Input input{reader,{}};return SurfaceExactPlan::build(input,base,device,blend,p);
}
int main(){unsigned cases=0;
 SurfaceExactPlan::Workspace initial,fresh;
 for(const auto& device:Data::DevicePatches)for(bool blend:{false,true})for(unsigned bits=0;bits<16;++bits){
  setup();assert(build(device.deviceID,true,initial));
  for(unsigned i=0;i<4;++i)if(bits&(1U<<i))put(base+initial.resolved[i].offset,initial.resolved[i].patched,initial.resolved[i].size);
  const unsigned changed=unsigned(bool(bits&1))+unsigned(bool(bits&2))+unsigned(bool(bits&8));
  const bool expected=changed==0||(changed==3&&(!blend||(bits&4)));
  const auto before=blocks;const bool result=build(device.deviceID,blend,fresh);
  assert(result==expected&&blocks==before);
  if(result){
   assert(fresh.count==(blend?4U:3U));
   assert(fresh.state==(changed==3?SurfaceExactPlan::State::Installed:SurfaceExactPlan::State::Ready));
   assert(SurfaceExactPlan::samePlan(fresh,fresh));
   if(!blend)for(unsigned i=0;i<fresh.count;++i)assert(fresh.sites[i].offset!=initial.resolved[2].offset);
   for(unsigned i=0;i<fresh.count;++i){const auto& p=fresh.sites[i];put(base+p.offset,p.patched,p.size);}
   assert(build(device.deviceID,blend,initial)&&initial.state==SurfaceExactPlan::State::Installed);
  }else assert(fresh.count==0&&fresh.state==SurfaceExactPlan::State::Rejected);
  ++cases;
 }
 for(unsigned fault=0;fault<5;++fault){
  setup();assert(build(0x1636,true,initial));
  if(fault==0)word32(base+88,0);
  if(fault==1)word32(imageAddresses[0]+0x38a048,0);
  if(fault==2){UInt8 bad=0;put(imageAddresses[0]+0x51829,&bad,1);}
  if(fault==3){UInt8 bad=0;put(functionAddresses[2],&bad,1);}
  if(fault==4)failedRead=base;
  const auto before=blocks;assert(!build(0x1636,true,fresh)&&fresh.count==0&&blocks==before);++cases;
 }
 setup();assert(!build(0x6863,true,fresh)&&fresh.count==0);++cases;
 // A precommit refresh must preserve saved bytes and selected ownership.
 setup();assert(build(0x1636,true,initial)&&build(0x1636,true,fresh));assert(SurfaceExactPlan::samePlan(initial,fresh));++cases;
 put(base+initial.resolved[2].offset,initial.resolved[2].patched,2);
 assert(build(0x1636,true,fresh)&&!SurfaceExactPlan::samePlan(initial,fresh));++cases;
 // When blend is off, its externally changed known gate remains unowned.
 setup();assert(build(0x1636,false,initial));put(base+initial.resolved[2].offset,initial.resolved[2].patched,2);
 assert(build(0x1636,false,fresh)&&SurfaceExactPlan::samePlan(initial,fresh));++cases;
 printf("PASS %u exact surface plan cases: six APUs, all16 native/patched combinations, both blend options, fresh-plan equality, identity rejection and no writes\n",cases);
}
'''
def main():
 with tempfile.TemporaryDirectory(prefix='nred-surface-plan-') as directory:
  p=Path(directory);(p/'IOKit').mkdir();(p/'libkern').mkdir()
  stub='#pragma once\n#include <cstdint>\nusing UInt8=uint8_t;using UInt32=uint32_t;using UInt64=uint64_t;\n'
  (p/'IOKit/IOTypes.h').write_text(stub);(p/'libkern/OSTypes.h').write_text(stub)
  (p/'test.cpp').write_text(SOURCE)
  subprocess.run(['xcrun','clang++','-std=c++23','-O1','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(p),'-I'+str(ROOT/'NootedRed'),'-I'+str(ROOT/'tools/fixtures'),str(p/'test.cpp'),'-o',str(p/'test')],check=True,timeout=90)
  subprocess.run([str(p/'test')],check=True,timeout=120)
if __name__=='__main__':main()
