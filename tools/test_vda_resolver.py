#!/usr/bin/env python3
"""Execute the production VDA page planner and wrapper under ASan/UBSan; no GPU."""
from pathlib import Path
import os,shlex,subprocess,tempfile
from test_patch_dispatch import method
ROOT=Path(__file__).resolve().parents[1]
SHIM=r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <stdexcept>
#include <string>
#include "VDASignaturePlanner.hpp"
using UInt8=uint8_t;using UInt32=uint32_t;using UInt64=uint64_t;using SInt32=int32_t;
#define PATH_MAX 1024
#define KERN_SUCCESS 0
#define PANIC_COND(c,...) do { if(c)throw std::runtime_error("write protection"); }while(0)
struct UserPatches {
 struct SignaturePatch {const UInt8* context;const UInt8* mask;size_t contextSize,patchOffset;const UInt8* replace;size_t replaceSize,skip,count;UInt64 pageOffset;bool glDriver=false;const UInt8* find=nullptr;size_t findSize=0;};
 bool vdaEnabled=true, vdaResolverEnabled=true;SInt32 vdaAppliedCount=0;
 void patchVDASignaturePage(const void*,UInt64,void*,bool);
};
constexpr size_t arrsize(const auto& a){return sizeof(a)/sizeof(a[0]);}
#include "VDASignatures.inc"
using vnode_t=void*;
const char* correctPath="/System/Library/Extensions/AMDRadeonVADriver2.bundle/Contents/MacOS/AMDRadeonVADriver2";
int vn_getpath(void* node,char* path,int* size){const auto* s=static_cast<const char*>(node);if(strlen(s)>=size_t(*size))return 1;strcpy(path,s);return 0;}
bool option=true,fair=false,ready=true;unsigned major=24;
bool checkKernelArgument(const char* s){return option&&!strcmp(s,"-NRedVDAResolve");}
void* current_task(){return nullptr;}bool isFairPlayClient(void*){return fair;}
struct Version{unsigned major(){return ::major;}};Version currentKernelVersion(){return {};}
struct VCNBridge{static VCNBridge& singleton(){static VCNBridge v;return v;}bool loadReady(){return ready;}};
struct KernelPatcher{static inline int kernelWriteLock=0;};
namespace MachInfo {bool enterFail=false,exitFail=false,writing=false,race=false;UInt8* racedPage=nullptr;
 int setKernelWriting(bool enable,int){if(enable&&enterFail)return 1;if(!enable&&exitFail)return 1;writing=enable;if(enable&&race){racedPage[109]^=1;race=false;}return 0;}}
SInt32 OSIncrementAtomic(SInt32* p){return (*p)++;}
struct NRed{static NRed& singleton(){static NRed n;return n;}void setProp32(const char*,UInt32){}};
'''
CASES=r'''
int main(){
 using namespace VDASignaturePlanner;
 UInt8 page[4096],original[4096];
 const auto& s=kVDAResolverSignatures_Modern[1];
 auto reset=[&]{memset(page,0xCC,sizeof(page));memcpy(page+100,s.context,s.contextSize);memcpy(original,page,sizeof(page));option=true;fair=false;ready=true;major=24;MachInfo::enterFail=MachInfo::exitFail=MachInfo::writing=MachInfo::race=false;};
 reset();Plan p;assert(build(page,kVDAResolverSignatures_Modern,kVDAResolverSignatureCount_Modern,0,p));assert(p.count==1&&p.sites[0].offset==109);
 for(auto& sig: kVDAResolverSignatures_Modern){
  reset();memset(page,0xCC,sizeof(page));memcpy(page+128,sig.context,sig.contextSize);
  assert(build(page,&sig,1,0,p)&&p.count==1);
  assert(p.sites[0].offset==128+sig.patchOffset&&p.sites[0].size==sig.findSize);
 }
 reset();auto broken=s;broken.patchOffset=SIZE_MAX;assert(!build(page,&broken,1,0,p)&&p.count==0);
 broken=s;broken.findSize=4096;assert(!build(page,&broken,1,0,p));
 broken=s;broken.count=0;assert(!build(page,&broken,1,0,p));
 broken=s;broken.contextSize=4097;assert(!build(page,&broken,1,0,p));
 broken=s;broken.pageOffset=4096;assert(!build(page,&broken,1,0,p));
 assert(!build(nullptr,&s,1,0,p));assert(!build(page,&s,17,0,p));
 // More occurrences than declared are ambiguous: no partial plan survives.
 reset();memcpy(page+200,s.context,s.contextSize);assert(!build(page,&s,1,0,p)&&p.count==0);
 // Even individually valid signatures must not overlap.
 reset();UserPatches::SignaturePatch overlap[]={s,s};assert(!build(page,overlap,2,0,p)&&p.count==0);
 // A context may wildcard relocations, but the actual instruction bytes stay exact.
 reset();UInt8 mask[23];memcpy(mask,s.mask,23);mask[9]=0;broken=s;broken.mask=mask;page[109]^=1;assert(!build(page,&broken,1,0,p)&&p.count==0);
 for(unsigned mode=0;mode<8;mode++){
  reset();UserPatches patcher;const char* path=correctPath;bool cache=false;
  switch(mode){case 0:patcher.vdaResolverEnabled=false;break;case 1:patcher.vdaEnabled=false;break;case 2:cache=true;break;case 3:ready=false;break;case 4:fair=true;break;case 5:path="/Applications/NotificationCenter-AMDRadeonVADriver2";break;case 6:major=26;break;case 7:MachInfo::enterFail=true;break;}
  patcher.patchVDASignaturePage(page,0,const_cast<char*>(path),cache);assert(!memcmp(page,original,sizeof(page))&&!patcher.vdaAppliedCount&&!MachInfo::writing);
 }
 reset();UserPatches patcher;patcher.patchVDASignaturePage(page,0,const_cast<char*>(correctPath),false);
 assert(!memcmp(page+109,s.replace,s.replaceSize)&&patcher.vdaAppliedCount==1&&!MachInfo::writing);
 for(size_t i=0;i<sizeof(page);i++)if(i<109||i>=109+s.replaceSize)assert(page[i]==original[i]);
 memcpy(original,page,sizeof(page));patcher.patchVDASignaturePage(page,0,const_cast<char*>(correctPath),false);assert(!memcmp(page,original,sizeof(page))&&patcher.vdaAppliedCount==1);
 reset();MachInfo::race=true;MachInfo::racedPage=page;UserPatches raced;raced.patchVDASignaturePage(page,0,const_cast<char*>(correctPath),false);assert(!raced.vdaAppliedCount&&!MachInfo::writing);
 reset();MachInfo::exitFail=true;bool panic=false;try{UserPatches failed;failed.patchVDASignaturePage(page,0,const_cast<char*>(correctPath),false);}catch(const std::runtime_error&){panic=true;}assert(panic);
 puts("VDA resolver: original sites, bounds/overflow/ambiguity/overlap rejection, exact path/cache/FairPlay/bridge/opt-in gates, locked revalidation, idempotency and fatal restore failure passed");
}
'''
def main():
 source=(ROOT/'NootedRed/UserPatches.cpp').read_text()
 with tempfile.TemporaryDirectory(prefix='nred-vda-resolver-') as directory:
  p=Path(directory);(p/'test.cpp').write_text(SHIM+method(source,'void UserPatches::patchVDASignaturePage(')+CASES)
  subprocess.run(shlex.split(os.environ.get('CXX','c++'))+['-std=c++20','-O1','-g','-fsanitize=address,undefined','-I'+str(ROOT/'NootedRed'),str(p/'test.cpp'),'-o',str(p/'test')],check=True)
  subprocess.run([str(p/'test')],check=True)
if __name__=='__main__':main()
