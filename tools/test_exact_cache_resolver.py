#!/usr/bin/env python3
"""Fault-test the UUID-pinned resolver path; synthetic memory only, no GPU work."""
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
#include <UserCacheResolver.hpp>
#include <UserVideoGuardTypes.hpp>
static std::map<std::string,unsigned> properties;
#include "user-cache-dynamic.hpp"
using Patch=UserVideoGuardTypes::Patch;
const UInt8 uuid[16]={1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16};
const UInt8 a[32]={0x55,0x48,0x89,0xe5,1,2,3,4,5,6,7,8,9,10,11,12};
const UInt8 b[32]={0x53,0x48,0x89,0xe7,0,0,0,0,10,11,12,13,14,15};
const UInt8 replacement[]={0x90};
const UserCacheResolver::ImageReference images[]={{"/test/image",sizeof("/test/image")}};
const UserCacheResolver::Reference refs[]={{4,0,0x3f80,0}};
const UserCacheResolver::Function functions[]={
 {0,0x3f80,a,sizeof(a),nullptr,0,nullptr,0},
 {0,0x6f80,b,sizeof(b),refs,1,refs,1}};
const Patch patches[]={{0,a,replacement,1}};
const UserCacheResolver::Location locations[]={{0,0}};
struct Plan{Patch patch;UInt8 old[32],changed[32],scan[4096];};
static void setup(){cache(images,functions);put(base+88,uuid,16);}
static bool resolve(Plan& p){UserSharedCache::Input in{reader,{}};in.scanBuffer=p.scan;
 return UserCacheResolver::resolveExact(in,base,uuid,images,functions,patches,locations,&p.patch,p.old,p.changed,32);}
int main(){Plan p{};unsigned cases=0;
 setup();assert(resolve(p)&&p.patch.offset==functionAddresses[0]-base&&p.old[0]==0x55&&p.changed[0]==0x90);++cases;
 put(base+p.patch.offset,p.patch.patched,1);assert(resolve(p));++cases;
 setup();word32(base+88,0);assert(!resolve(p));++cases;
 setup();word32(base,0);assert(!resolve(p));++cases;
 for(unsigned f=0;f<2;++f)for(unsigned off=0;off<32;++off){
  setup();UInt8 v;assert(!reader(functionAddresses[f]+off,&v,1));v^=0x80;put(functionAddresses[f]+off,&v,1);
  assert(!resolve(p));++cases;
 }
 setup();failedRead=base+88; // Full header read still works; fail the actual mandatory header address.
 failedRead=base;assert(!resolve(p));++cases;
 // A valid function elsewhere cannot satisfy an incorrect exact RVA.
 setup();std::vector<UInt8> moved(a,a+sizeof(a));put(imageAddresses[0]+0x10000,moved.data(),moved.size());
 UInt8 bad=0;put(functionAddresses[0],&bad,1);assert(!resolve(p));++cases;
 // Repeated successful use never authorizes a later modified page.
 setup();assert(resolve(p));bad=0xff;put(functionAddresses[1]+31,&bad,1);assert(!resolve(p));++cases;
 printf("PASS %u exact resolver cases: UUID/magic, stock/patched, every code/displacement byte, missing header, moved function and fresh revalidation\n",cases);
}
'''
def main():
 with tempfile.TemporaryDirectory(prefix='nred-exact-resolver-') as directory:
  p=Path(directory);(p/'IOKit').mkdir();(p/'libkern').mkdir()
  stub='#pragma once\n#include <cstdint>\nusing UInt8=uint8_t;using UInt32=uint32_t;using UInt64=uint64_t;\n'
  (p/'IOKit/IOTypes.h').write_text(stub);(p/'libkern/OSTypes.h').write_text(stub)
  (p/'test.cpp').write_text(SOURCE)
  subprocess.run(['xcrun','clang++','-std=c++23','-O1','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(p),'-I'+str(ROOT/'NootedRed'),'-I'+str(ROOT/'tools/fixtures'),str(p/'test.cpp'),'-o',str(p/'test')],check=True,timeout=90)
  subprocess.run([str(p/'test')],check=True,timeout=60)
if __name__=='__main__':main()
