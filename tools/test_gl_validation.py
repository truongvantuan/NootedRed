#!/usr/bin/env python3
"""Exercise actual combined validation wrappers; preserve GL/VDA identity and native outputs."""
from pathlib import Path
import os,shlex,subprocess,tempfile
from test_patch_dispatch import method
ROOT=Path(__file__).resolve().parents[1]
SHIM=r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <vector>
#include <cstdio>
using UInt8=uint8_t;using UInt64=uint64_t;using boolean_t=int;
static int validValue=1,taintValue=0,nxValue=0,resultValue=1,nativeCalls=0;
struct Record{const void* data;UInt64 offset;bool cache;};static std::vector<Record> records;
static void* expectedVnode;static void* expectedPager;static const void* expectedData;
static UInt64 expectedOffset,expectedSize;
struct UserOpenGL {static constexpr UInt64 MaxFileSize=32*1024*1024;};
static void originalPage(void* vnode,void* pager,UInt64 offset,const void* data,int* valid,int* taint,int* nx){
 assert(records.empty()&&vnode==expectedVnode&&pager==expectedPager&&offset==expectedOffset&&data==expectedData);
 nativeCalls++;if(valid)*valid=validValue;if(taint)*taint=taintValue;if(nx)*nx=nxValue;
}
static boolean_t originalRange(void* vnode,void* pager,UInt64 offset,const void* data,UInt64 size,unsigned* taint){
 assert(records.empty()&&vnode==expectedVnode&&pager==expectedPager&&offset==expectedOffset&&data==expectedData&&size==expectedSize);
 nativeCalls++;if(taint)*taint=taintValue;return resultValue;
}
class UserPatches {
 public:
 static constexpr size_t kPageSize=4096;
 static UserPatches& singleton(){static UserPatches p;return p;}
 uintptr_t orgCsValidatePage=reinterpret_cast<uintptr_t>(&originalPage);
 uintptr_t orgCsValidateRange=reinterpret_cast<uintptr_t>(&originalRange);
 bool isGLDriverVnode(void* vnode) const {return vnode&&!strcmp(static_cast<const char*>(vnode),"AMDRadeonX5000GLDriver");}
 void patchNativePage(const void* data,UInt64 offset,void*,bool cache){assert(nativeCalls==1);records.push_back({data,offset,cache});}
 static void wrapCsValidatePage(void*,void*,UInt64,const void*,int*,int*,int*);
 static boolean_t wrapCsValidateRange(void*,void*,UInt64,const void*,UInt64,unsigned*);
};
#define FunctionCast(name,pointer) reinterpret_cast<decltype(&name)>(pointer)
BODY
static void reset(const char* name,const void* data,UInt64 offset,UInt64 size=0){
 records.clear();nativeCalls=0;expectedVnode=const_cast<char*>(name);expectedPager=reinterpret_cast<void*>(0x123456789ULL);
 expectedData=data;expectedOffset=offset;expectedSize=size;
}
int main(){unsigned cases=0;UInt8 bytes[8192]{};
 for(int valid:{0,1,2,3,7,15,31})for(int taint:{0,1})for(int nx:{0,1})for(bool aligned:{false,true})
 for(unsigned missing=0;missing<4;missing++){
  validValue=valid;taintValue=taint;nxValue=nx;auto offset=aligned?0xe000:0xe001;
  reset("AMDRadeonX5000GLDriver",bytes,offset);int v=-8,t=-8,n=-8;
  UserPatches::wrapCsValidatePage(expectedVnode,expectedPager,offset,bytes,missing==1?nullptr:&v,missing==2?nullptr:&t,missing==3?nullptr:&n);
  bool allowed=(valid==1||valid==15)&&taint==0&&nx==0&&aligned&&missing==0;
  assert(records.size()==unsigned(allowed)&&nativeCalls==1);
  if(missing!=1)assert(v==valid);if(missing!=2)assert(t==taint);if(missing!=3)assert(n==nx);cases++;
 }
 for(const char* name:{"AMDRadeonX5000GLDriver","dyld_shared_cache_x86_64h"})
 for(UInt64 offset:{UInt64(0xe000),UInt64(0xe001),UInt64(0x3087b3000),UInt64(0xfffffffffffff000ULL)})
 for(UInt64 size:{UInt64(0),UInt64(4095),UInt64(4096),UInt64(8192),UInt64(8193)})
 for(int success:{0,1})for(int taint:{0,1})for(bool missing:{false,true}){
  resultValue=success;taintValue=taint;reset(name,bytes,offset,size);unsigned t=99;
  int result=UserPatches::wrapCsValidateRange(expectedVnode,expectedPager,offset,bytes,size,missing?nullptr:&t);
  bool allowed=success&&!taint&&!missing&&!(offset&4095)&&size<=~UInt64(0)-offset;
  if(!strcmp(name,"AMDRadeonX5000GLDriver")) allowed=allowed&&offset<=UserOpenGL::MaxFileSize&&size<=UserOpenGL::MaxFileSize-offset;
  assert(result==success&&nativeCalls==1&&records.size()==(allowed?size/4096:0));
  if(!missing)assert(t==unsigned(taint));
  for(size_t i=0;i<records.size();i++){
   assert(records[i].offset==offset+i*4096&&records[i].data==bytes+i*4096);
   assert(records[i].cache==(strcmp(name,"AMDRadeonX5000GLDriver")!=0));
  }cases++;
 }
 reset("AMDRadeonX5000GLDriver",nullptr,0xe000,4096);resultValue=1;taintValue=0;unsigned t=99;
 UserPatches::wrapCsValidateRange(expectedVnode,expectedPager,0xe000,nullptr,4096,&t);assert(records.empty());cases++;
 printf("PASS %u production validation cases: native outputs/order, 1/0xF bitmap, taint/NX/nulls, alignment/overflow, GL range identity and large VDA cache offsets\n",cases);
}
'''
def main():
 source=(ROOT/'NootedRed/UserPatches.cpp').read_text()
 bodies='\n'.join(method(source,name) for name in ['__attribute__((noinline)) void UserPatches::wrapCsValidatePage(', '__attribute__((noinline)) boolean_t UserPatches::wrapCsValidateRange('])
 with tempfile.TemporaryDirectory(prefix='nred-gl-validation-') as tmp:
  p=Path(tmp);(p/'test.cpp').write_text(SHIM.replace('BODY',bodies));c=shlex.split(os.environ.get('CXX','clang++'))
  subprocess.run(c+['-std=c++17','-O2','-Wall','-Wextra',str(p/'test.cpp'),'-o',str(p/'test')],check=True,timeout=60)
  subprocess.run([str(p/'test')],check=True,timeout=60)
if __name__=='__main__':main()
