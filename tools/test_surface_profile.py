#!/usr/bin/env python3
"""Validate current-build surface references and execute CPU-only scratch topology code."""
from pathlib import Path
import ctypes,mmap,re,struct,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
SOURCE=r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <map>
#include <vector>
#include <set>
#include <string>
#include <UserSurface24H232Data.hpp>
static std::map<std::string,unsigned> properties;
#include "user-cache-dynamic.hpp"
using namespace UserSurface24H232Data;
struct Plan {Patch patches[4];UInt8 original[4][512],patched[4][512],scan[4096];};
static bool resolve(const Patch* patches,Plan& p){UserSharedCache::Input in{reader,{}};in.scanBuffer=p.scan;
 return UserCacheResolver::resolve(in,base,ResolverImages,ResolverFunctions,patches,ResolverLocations,p.patches,
  &p.original[0][0],&p.patched[0][0],512);
}
static void setup(){cache(ResolverImages,ResolverFunctions);}
static void apply(Plan& p){for(const auto& patch:p.patches)put(base+patch.offset,patch.patched,patch.size);}
int main(){unsigned cases=0;
 for(const auto& device:DevicePatches){
  setup();Plan p{};assert(resolve(device.patches,p));++cases;
  for(unsigned i=0;i<4;++i){auto& patch=p.patches[i];UInt8 b[512];assert(!reader(base+patch.offset,b,patch.size));assert(!memcmp(b,patch.original,patch.size));}
  apply(p);assert(resolve(device.patches,p));++cases;
  // A previously installed local LegacyBlend is an explicitly recognized variant.
  setup();assert(resolve(device.patches,p));put(base+p.patches[2].offset,p.patches[2].patched,2);
  assert(resolve(device.patches,p));++cases;
  for(unsigned f=0;f<5;++f){
   const auto& fn=ResolverFunctions[f];
   for(unsigned off:{0U,fn.size/2,fn.size-1}){
    if(UserCacheResolver::skipped(off,fn.originalRefs,fn.originalCount))continue;
    setup();UInt8 b;assert(!reader(functionAddresses[f]+off,&b,1));b^=0x80;put(functionAddresses[f]+off,&b,1);
    assert(!resolve(device.patches,p));++cases;
   }
   for(unsigned r=0;r<fn.originalCount;++r){
    setup();UInt8 b;const auto& ref=fn.originalRefs[r];auto addr=functionAddresses[f]+ref.offset;
    // A changed GOT address can legitimately alias the same symbol. Corrupt
    // its bound identity instead; direct targets must retain the exact identity.
    if(ref.indirect){
     UInt8 field[8];UInt64 target=0;assert(!reader(addr,field,4));
     assert(UserSharedCache::relativeTarget(addr,0,field,target));
     if(ref.indirect==2){assert(!reader(target+2,field,4));UInt64 slot=0;
      assert(UserSharedCache::relativeTarget(target+2,0,field,slot));target=slot;}
     assert(!reader(target,field,8));word64(target,UserSharedCache::wide(field)^0x80);
     assert(!resolve(device.patches,p));++cases;continue;
    }
    assert(!reader(addr,&b,1));b^=0x80;put(addr,&b,1);
    if(resolve(device.patches,p)){fprintf(stderr,"unexpected reference acceptance device=%x function=%u ref=%u off=%u\n",device.deviceID,f,r,fn.originalRefs[r].offset);return 1;}++cases;
   }
  }
  // Missing function contents, unrelated device selection and byte damage fail closed.
  setup();failedRead=functionAddresses[3];assert(!resolve(device.patches,p));++cases;
 }
 assert(!findDevice(0x6863)&&!findDevice(0)&&!findDevice(0xffff1638));
 printf("PASS %u surface reference cases: all device variants, complete functions, every external reference, already-patched/local blend and missing bytes\n",cases);
}
'''
def data_array(text,name):
 body=re.search(r'inline constexpr UInt8 '+name+r'\[\] = \{(.*?)\};',text,re.S)
 assert body is not None,name
 return bytes(int(v,16) for v in re.findall(r'0x([0-9a-fA-F]{2})',body[1]))
def function(code):
 prefix=bytes.fromhex('415541564989fe4531ed');suffix=bytes.fromhex('415e415dc3')
 memory=mmap.mmap(-1,mmap.PAGESIZE,prot=mmap.PROT_READ|mmap.PROT_WRITE)
 address=ctypes.addressof(ctypes.c_char.from_buffer(memory));memory.write(prefix+code+suffix)
 libc=ctypes.CDLL(None);libc.mprotect.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int]
 assert libc.mprotect(address,mmap.PAGESIZE,mmap.PROT_READ|mmap.PROT_EXEC)==0
 return memory,ctypes.CFUNCTYPE(ctypes.c_uint32,ctypes.c_void_p)(address)
def native_cases():
 text=(ROOT/'NootedRed/UserSurface24H232Data.hpp').read_text().split('namespace Submit {')[0]
 devices=[0x1638,0x15d8,0x15dd,0x15e7,0x1636,0x164c];cases=0
 original=data_array(text,'Original3');assert len(original)==456
 oldmem,old=function(original[0x55:0x69])
 try:
  for target in devices:
   changed=data_array(text,f'Scratch{target:04X}')
   assert len(changed)==456 and changed[0xd6:]==original[0xd6:]
   memory,new=function(changed[0x50:0x6f])
   try:
    # All 16-bit PCI IDs: the optimization must remain specific to this APU.
    for device in range(65536):
     info=ctypes.create_string_buffer(0xb0)
     struct.pack_into('<I',info,12,device);struct.pack_into('<I',info,0x60,8)
     struct.pack_into('<I',info,0x78,4);struct.pack_into('<I',info,0x80,2)
     assert old(info)==64 and new(info)==(16 if device==target else 64);cases+=1
    for device in [target,0x6863,0xffff1638]:
     for engines in [0,1,4,8,0xffffffff]:
      for arrays in [0,1,2,0xffffffff]:
       for units in [0,4,8,0xffffffff]:
        info=ctypes.create_string_buffer(0xb0)
        for off,val in [(12,device),(0x60,units),(0x78,engines),(0x80,arrays)]:struct.pack_into('<I',info,off,val)
        assert old(info)==(engines*arrays*units)&0xffffffff
        assert new(info)==((1 if device==target else engines)*arrays*units)&0xffffffff;cases+=1
   finally:memory.close()
 finally:oldmem.close()
 print(f'PASS {cases} native CPU scratch cases: all PCI IDs, own-device-only topology, unsigned overflow and unchanged allocation/free tail')
def main():
 with tempfile.TemporaryDirectory(prefix='nred-surface-reference-') as directory:
  p=Path(directory);(p/'IOKit').mkdir();(p/'libkern').mkdir()
  stub='#pragma once\n#include <cstdint>\nusing UInt8=uint8_t;using UInt32=uint32_t;using UInt64=uint64_t;\n'
  (p/'IOKit/IOTypes.h').write_text(stub);(p/'libkern/OSTypes.h').write_text(stub)
  (p/'test.cpp').write_text(SOURCE)
  subprocess.run(['xcrun','clang++','-std=c++23','-O1','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(p),'-I'+str(ROOT/'NootedRed'),'-I'+str(ROOT/'tools/fixtures'),str(p/'test.cpp'),'-o',str(p/'test')],check=True,timeout=90)
  subprocess.run([str(p/'test')],check=True,timeout=90)
 native_cases()
if __name__=='__main__':main()
