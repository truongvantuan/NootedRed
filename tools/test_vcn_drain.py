#!/usr/bin/env python3
"""Execute native teardown delegation without polling or sleeping; no GPU/kernel."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
from test_patch_dispatch import method
ROOT=Path(__file__).resolve().parents[1]
SHIM=r'''
#include <cstdint>
#include <cassert>
#include <cstdio>
using UInt32=uint32_t;using UInt64=uintptr_t;
struct IOService {};
struct NRed {static NRed& singleton(){static NRed n;return n;}void setProp32(const char*,UInt32 v){assert(v==0);}};
struct VCNBridge {
 bool enabled=true,engineAllocated=true;void* hardwareHandle=(void*)3;void* vcnEngine=(void*)4;
 UInt64 orgAcceleratorStop=0,clientStop5000=0,orgClientStop=0;
 static VCNBridge& singleton(){static VCNBridge b;return b;}
 bool engineEnabled(){return enabled;}
 static void acceleratorStop(void*,IOService*);static void clientStop(void*,void*);
};
#define FunctionCast(name,address) reinterpret_cast<decltype(&name)>(address)
int bridged=0,native=0,accel=0;
void clientBridged(void* self,void* provider){assert(self==(void*)1&&provider==(void*)2);++bridged;}
void clientNative(void* self,void* provider){assert(self==(void*)1&&provider==(void*)2);++native;}
void accelNative(void* self,IOService* provider){assert(self==(void*)1&&provider==(IOService*)2);assert(VCNBridge::singleton().engineAllocated);++accel;}
'''
CASES=r'''
int main(){auto& b=VCNBridge::singleton();
 b.clientStop5000=(UInt64)&clientBridged;b.orgClientStop=(UInt64)&clientNative;b.orgAcceleratorStop=(UInt64)&accelNative;
 for(int i=0;i<100;++i){b.enabled=i%2;VCNBridge::clientStop((void*)1,(void*)2);}
 assert(bridged==50&&native==50&&b.engineAllocated);
 VCNBridge::acceleratorStop((void*)1,(IOService*)2);
 assert(accel==1&&!b.engineAllocated&&!b.hardwareHandle&&!b.vcnEngine);
 puts("VCN teardown: direct native/bridge forwarding, exactly once, cleanup after native stop; no idle polling or sleeps");
}
'''
def main():
 source=(ROOT/'NootedRed/VCNBridge.cpp').read_text()
 bodies=[method(source,s) for s in ('void VCNBridge::acceleratorStop(','void VCNBridge::clientStop(')]
 assert 'drainVCN(' not in source
 assert 'vcnIsIdle' not in source
 for body in bodies:
  assert 'IOSleep' not in body and 'while (' not in body and 'for (' not in body
 with tempfile.TemporaryDirectory(prefix='nred-vcn-teardown-') as temp:
  p=Path(temp);(p/'test.cpp').write_text(SHIM+'\n'.join(bodies)+CASES)
  subprocess.run(shlex.split(os.environ.get('CXX','c++'))+['-std=c++17','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(p/'test.cpp'),'-o',str(p/'test')],check=True)
  subprocess.run([str(p/'test')],check=True)
if __name__=='__main__':main()
