#!/usr/bin/env python3
"""Execute VCN GFXOFF hooks with simulated bridge transitions; never accesses a GPU."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
from test_patch_dispatch import method

ROOT=Path(__file__).resolve().parents[1]
SHIM=r'''
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <string>
using UInt32=uint32_t; using UInt64=uint64_t;
#define SYSLOG(...) do {} while (0)
#define FunctionCast(name,pointer) reinterpret_cast<decltype(&name)>(pointer)
struct NRed {
 std::map<std::string,UInt32> props;
 static NRed& singleton() { static NRed n; return n; }
 void setProp32(const char* name,UInt32 value) { props[name]=value; }
};
int originalCalls=0,notifyCalls=0;
void originalEnable(void*) { ++originalCalls; }
void notifyAccess(void*) { ++notifyCalls; }
class VCNBridge {
public:
 bool noGfxOff=false,gfxOffHeld=false,engine=false;
 void* hardwareHandle=reinterpret_cast<void*>(1);
 UInt64 enableGfxOff5000=reinterpret_cast<UInt64>(&originalEnable);
 UInt64 notifyGfxAccess=reinterpret_cast<UInt64>(&notifyAccess);
 static VCNBridge& singleton() { static VCNBridge b; return b; }
 bool engineEnabled() const { return engine; }
 static void noopEnableGfxOff(void*);
 void holdGfxOff();
};
void require(bool ok,const char* what) { if(!ok) { std::fprintf(stderr,"FAIL: %s\n",what);std::exit(1); } }
'''
CASES=r'''
int main() {
 auto& b=VCNBridge::singleton();
 auto reset=[&]() { b=VCNBridge{};originalCalls=notifyCalls=0;NRed::singleton().props.clear(); };
 reset(); b.noGfxOff=true;
 b.noopEnableGfxOff(b.hardwareHandle);
 require(originalCalls==1 && !b.gfxOffHeld,"unready bridge must preserve native GFXOFF");
 reset(); b.engine=true;
 b.noopEnableGfxOff(b.hardwareHandle);
 require(originalCalls==1 && !b.gfxOffHeld,"missing opt-in must preserve native GFXOFF");
 reset(); b.noGfxOff=b.engine=true;
 b.holdGfxOff();b.holdGfxOff();
 require(notifyCalls==1 && b.gfxOffHeld,"active bridge holds GFXOFF once");
 b.noopEnableGfxOff(b.hardwareHandle);
 require(originalCalls==0,"active requested bridge suppresses enableGfxOff");
 b.engine=false;b.noopEnableGfxOff(b.hardwareHandle);
 require(originalCalls==1 && !b.gfxOffHeld && NRed::singleton().props["NRedVCNGfxOffHeld"]==0,
         "bridge failure releases suppression and clears active hold marker");
 b.holdGfxOff();require(notifyCalls==1,"failed engine must not reacquire hold");
 reset();b.noGfxOff=true;b.holdGfxOff();
 require(notifyCalls==0 && !b.gfxOffHeld,"unready bridge cannot claim a hardware hold");
 reset();b.noGfxOff=b.engine=true;b.notifyGfxAccess=0;b.holdGfxOff();
 require(!b.gfxOffHeld,"unresolved notify method cannot claim a hold");
 reset();b.noGfxOff=b.engine=true;b.hardwareHandle=nullptr;b.holdGfxOff();
 require(!b.gfxOffHeld,"missing hardware handle cannot claim a hold");
 std::puts("production VCN GFXOFF: opt-in, ready/failed engine, one-shot hold and native fallback passed");
}
'''

def main():
 source=(ROOT/'NootedRed/VCNBridge.cpp').read_text()
 bodies='\n'.join(method(source,n) for n in ['void VCNBridge::noopEnableGfxOff(', 'void VCNBridge::holdGfxOff('])
 with tempfile.TemporaryDirectory(prefix='nred-gfxoff-') as directory:
  path=Path(directory);(path/'test.cpp').write_text(SHIM+bodies+CASES)
  subprocess.run(shlex.split(os.environ.get('CXX','c++'))+['-std=c++17','-Wall','-Wextra',str(path/'test.cpp'),'-o',str(path/'test')],check=True)
  subprocess.run([str(path/'test')],check=True)

if __name__=='__main__':main()
