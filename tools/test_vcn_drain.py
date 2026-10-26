#!/usr/bin/env python3
"""Execute production teardown drain with a simulated engine; no GPU or kernel access."""
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
#include <map>
#include <string>
using UInt32=uint32_t;using UInt64=uint64_t;
#define SYSLOG(...) do {} while(0)
constexpr UInt32 kDrainTimeoutMs=250,kDrainStepMs=5;
struct NRed { std::map<std::string,UInt32> props;
 static NRed& singleton(){static NRed n;return n;}
 void setProp32(const char* k,UInt32 v){props[k]=v;}
};
int elapsed=0,queries=0,idleAt=0;
void IOSleep(UInt32 ms){elapsed+=ms;}
bool idle(void* engine){assert(engine==(void*)1);++queries;return elapsed>=idleAt;}
class VCNBridge { public:
 bool enabled=true,noDrain=false;void* vcnEngine=(void*)1;
 UInt64 vcnIsIdle=reinterpret_cast<UInt64>(&idle);
 UInt32 drainCount=0,drainTimeouts=0,lastWaitMs=0,maxWaitMs=0;
 static VCNBridge& singleton(){static VCNBridge b;return b;}
 bool engineEnabled()const{return enabled;}
 void drainVCN(const char*);
};
'''
CASES=r'''
int main(){auto& b=VCNBridge::singleton();
 auto reset=[&](){b=VCNBridge{};elapsed=queries=idleAt=0;NRed::singleton().props.clear();};
 for(int delay : {0,5,40,245,250,251,1000}){
  reset();idleAt=delay;b.drainVCN("test");
  assert(elapsed==(delay>250?250:delay));assert(b.lastWaitMs==elapsed);
  assert(b.drainCount==1&&b.drainTimeouts==(delay>250?1:0));
  assert(queries<=51&&b.maxWaitMs==elapsed);
 }
 for(int disabled=0;disabled<4;++disabled){reset();
  if(disabled==0)b.enabled=false;if(disabled==1)b.noDrain=true;
  if(disabled==2)b.vcnEngine=nullptr;if(disabled==3)b.vcnIsIdle=0;
  b.drainVCN("disabled");assert(!elapsed&&!queries&&!b.drainCount);
 }
 reset();idleAt=1000;b.drainVCN("timeout");assert(b.drainTimeouts==1);
 idleAt=elapsed+5;b.drainVCN("retry");assert(b.drainCount==2&&b.drainTimeouts==1&&b.lastWaitMs==5&&b.maxWaitMs==250);
 puts("VCN drain: idle/delayed/timeout/250ms bound/opt-out/missing engine or symbol/retry passed");
}
'''
def main():
 source=(ROOT/'NootedRed/VCNBridge.cpp').read_text()
 for signature in ('void VCNBridge::acceleratorStop(', 'void VCNBridge::clientStop('):
  body=method(source,signature)
  assert body.index('drainVCN(')<body.index('FunctionCast(') if 'FunctionCast(' in body else body.index('drainVCN(')<body.index('const auto address')
 with tempfile.TemporaryDirectory(prefix='nred-vcn-drain-') as temp:
  path=Path(temp);(path/'test.cpp').write_text(SHIM+method(source,'void VCNBridge::drainVCN(')+CASES)
  subprocess.run(shlex.split(os.environ.get('CXX','c++'))+['-std=c++17','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(path/'test.cpp'),'-o',str(path/'test')],check=True)
  subprocess.run([str(path/'test')],check=True)
if __name__=='__main__':main()
