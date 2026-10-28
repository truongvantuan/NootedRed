#!/usr/bin/env python3
"""Verify native argument/result forwarding and logging bound without GPU work."""
import re
import subprocess
import tempfile
from pathlib import Path
from test_patch_dispatch import method

ROOT = Path(__file__).resolve().parents[1]
SHIM = r'''
#include <cstdint>
#include <cassert>
#include <cstring>
using UInt32=uint32_t;using SInt32=int32_t;using UInt64=uint64_t;
using mach_vm_address_t=uintptr_t;
static unsigned logs=0,calls=0;
#define SYSLOG(...) do { ++logs; } while(0)
int proc_selfpid(){return 501;}
int OSIncrementAtomic(volatile SInt32* p){int old=*p;*p=old+1;return old;}
class VCNBridge { public:
 bool traceContexts=false;
 mach_vm_address_t orgVideoNewContext=0,orgVideoRemoveContext=0;
 static VCNBridge& singleton(){static VCNBridge b;return b;}
 static UInt32 videoNewContext(void*,void*,void*,UInt64,UInt64*);
 static UInt32 videoRemoveContext(void*,void*);
};
UInt32 nativeNew(void* self,void* in,void* out,UInt64 size,UInt64* outSize){
 assert(self==(void*)1&&in==(void*)2&&out==(void*)3&&size==0xfedcba9876543210ULL);
 *outSize=0x123456789abcdef0ULL;++calls;return 0xe00002c2;
}
UInt32 nativeRemove(void* self,void* in){assert(self==(void*)1&&in==(void*)2);++calls;return 0xe00002c0;}
'''
CASES = r'''
int main(){
 auto& b=VCNBridge::singleton();b.orgVideoNewContext=(uintptr_t)&nativeNew;b.orgVideoRemoveContext=(uintptr_t)&nativeRemove;
 for(bool enabled:{false,true}){
  b.traceContexts=enabled;logs=calls=0;
  for(unsigned i=0;i<600;++i){
   UInt64 outSize=0;
   assert(VCNBridge::videoNewContext((void*)1,(void*)2,(void*)3,0xfedcba9876543210ULL,&outSize)==0xe00002c2);
   assert(outSize==0x123456789abcdef0ULL);
   assert(VCNBridge::videoRemoveContext((void*)1,(void*)2)==0xe00002c0);
  }
  assert(calls==1200);assert(logs==(enabled?1024u:0u));
 }
}
'''


def main():
    source = (ROOT/'NootedRed/VCNBridge.cpp').read_text()
    bodies = '\n'.join(method(source, signature) for signature in [
        'UInt32 contextTraceBegin(', 'UInt32 VCNBridge::videoNewContext(',
        'UInt32 VCNBridge::videoRemoveContext('])
    with tempfile.TemporaryDirectory(prefix='nred-context-trace-') as directory:
        root = Path(directory)
        (root/'test.cpp').write_text('#include <initializer_list>\n'+SHIM+bodies+CASES)
        subprocess.run(['c++','-std=c++17','-fsanitize=address,undefined',str(root/'test.cpp'),'-o',str(root/'test')],check=True)
        subprocess.run([str(root/'test')],check=True)
    print('Context trace: full-width arguments, output pointer, native errors, opt-out and 512-event log bound passed')


if __name__ == '__main__':
    main()
