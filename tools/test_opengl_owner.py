#!/usr/bin/env python3
"""Execute the real conditional GL writer with fault injection; no kernel/GPU access."""
from pathlib import Path
import os,shlex,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
SHIM=r'''
#include <cassert>
#include <array>
#include <map>
#include <set>
#include <functional>
#include <string>
#include <cstdio>
#include <UserOpenGL.hpp>
#include <UserOpenGLResolver.hpp>
using thread_call_param_t=void*;using thread_call_t=void*;using Callback=void(*)(void*,void*);
constexpr int KERN_SUCCESS=0,THREAD_CALL_PRIORITY_KERNEL=1,THREAD_CALL_OPTIONS_ONCE=1;
static bool locked=false,inHook=false,pending=false,allocateOK=true;
static unsigned writes=0,queued=0,allocated=0;
static std::set<unsigned> failures;static std::function<void()> race;static Callback callback=nullptr;
static std::map<std::string,unsigned> props;
struct NRed{static NRed& singleton(){static NRed n;return n;}
 void setProp32(const char* key,unsigned value){assert(!locked&&!inHook);props[key]=value;}};
struct KernelPatcher{static constexpr void* kernelWriteLock=nullptr;};
namespace MachInfo {static int setKernelWriting(bool enable,void*){
 writes++;if(enable){assert(!locked);locked=true;if(race){auto f=race;race=nullptr;f();}}
 else assert(locked);
 if(failures.contains(writes)){locked=false;return 5;}
 if(!enable)locked=false;return 0;
}}
static thread_call_t thread_call_allocate_with_options(Callback f,void*,int priority,int options){
 assert(priority==1&&options==1);allocated++;callback=f;return allocateOK?reinterpret_cast<void*>(1):nullptr;}
static void thread_call_enter(thread_call_t call){assert(call&&!locked);pending=true;queued++;}
static void flush(){assert(!inHook&&!locked);if(pending){pending=false;callback(nullptr,nullptr);}}
BODY
static void reset(unsigned major=24,unsigned pci=0x1636,bool dynamic=true,bool force=false){
 device=nullptr;reportCall=nullptr;appliedMask=dynamicMask=errorMask=0;
 locked=inHook=pending=false;allocateOK=true;writes=queued=allocated=0;failures.clear();race=nullptr;props.clear();
 UserOpenGL::init(major,pci,dynamic,force);assert(!pending&&queued==0);
}
static void apply(void* bytes,uint64_t offset){inHook=true;UserOpenGL::patchPage(bytes,offset);inHook=false;}
int main(){unsigned cases=0;
 for(const auto& d:UserOpenGLData::Devices)for(unsigned k=0;k<2;k++){
  reset(d.major,d.deviceID);auto off=d.patches[k].offset-d.pages[k].offset;
  std::array<uint8_t,4096> bytes;memcpy(bytes.data(),d.pages[k].original,4096);auto before=bytes;
  apply(bytes.data(),off);assert(!locked&&props.count("NRedOpenGLSEApplied")==0&&pending);flush();
  assert(writes==2&&!memcmp(bytes.data()+d.pages[k].offset,d.pages[k].patched,d.pages[k].size));
  auto n=queued;apply(bytes.data(),off);flush();assert(writes==2&&queued==n);cases++;
  // Acquire failure, one restore failure, repeated restore failure; never publish success on failure.
  for(auto fail: {std::set<unsigned>{1},std::set<unsigned>{2},std::set<unsigned>{2,4}}){
   reset(d.major,d.deviceID);bytes=before;failures=fail;apply(bytes.data(),off);flush();assert(!locked);
   if(fail.contains(1)){assert(bytes==before&&props.at("NRedOpenGLWriteRejected")==1);}
   else if(fail.contains(4)){assert(props.at("NRedOpenGLRestoreFailed")==1&&appliedMask==0);}
   else {assert(appliedMask==(1U<<k)&&writes==4);}
   cases++;
  }
  reset(d.major,d.deviceID);bytes=before;race=[&]{bytes[d.pages[k].offset]^=1;};
  apply(bytes.data(),off);flush();assert(appliedMask==0&&writes==2);cases++;
  // Dynamic-only and exact-only policies preserve existing QA/disable controls.
  reset(d.major,d.deviceID,false);bytes=before;bytes[(d.pages[k].offset+d.pages[k].size)%4096]^=1;
  auto changed=bytes;apply(bytes.data(),off);assert(bytes==changed&&writes==0);cases++;
  reset(d.major,d.deviceID,true,true);bytes=before;apply(bytes.data(),off);flush();
  assert(dynamicMask==(1U<<k)&&appliedMask==(1U<<k));cases++;
  reset(d.major,d.deviceID);bytes=before;apply(bytes.data(),0x2000000);assert(bytes==before&&writes==0);cases++;
 }
 reset(22);assert(device==nullptr&&allocated==0);reset(24,0xffff);assert(device==nullptr&&allocated==0);
 reset();reportCall=nullptr;allocated=0;allocateOK=false;UserOpenGL::init(24,0x1636,true,false);
 assert(props.at("NRedOpenGLRejected")==1&&!reportCall);cases+=3;
 reset();inHook=true;UserOpenGL::reportBudgetResult(true,true);inHook=false;flush();assert(props.at("NRedGLBudgetApplied")==1);
 inHook=true;UserOpenGL::reportBudgetResult(false,false);inHook=false;flush();assert(props.at("NRedOpenGLRestoreFailed")==1);cases+=2;
 printf("PASS %u production GL owner cases: all OS/APUs, writes, races, restore retry/failure, async diagnostics, exact/QA controls and budget reporting\n",cases);
}
'''
def main():
 source=(ROOT/'NootedRed/UserOpenGL.cpp').read_text();source='\n'.join(x for x in source.splitlines() if not x.startswith('#include'))
 with tempfile.TemporaryDirectory(prefix='nred-gl-owner-') as tmp:
  p=Path(tmp);(p/'IOKit').mkdir();(p/'libkern').mkdir()
  (p/'IOKit/IOTypes.h').write_text('#pragma once\n#include <cstdint>\nusing UInt8=uint8_t;using UInt32=uint32_t;using UInt64=uint64_t;\n')
  (p/'libkern/libkern.h').write_text('#pragma once\n#include <cstring>\n')
  (p/'test.cpp').write_text(SHIM.replace('BODY',source))
  compiler=shlex.split(os.environ.get('CXX','clang++'))
  subprocess.run(compiler+['-std=c++23','-O2','-Wall','-Wextra','-Werror','-I'+str(p),'-I'+str(ROOT/'NootedRed'),str(p/'test.cpp'),'-o',str(p/'test')],check=True,timeout=60)
  subprocess.run([str(p/'test')],check=True,timeout=60)
if __name__=='__main__':main()
