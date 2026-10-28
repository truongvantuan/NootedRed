#!/usr/bin/env python3
"""Execute production hook installation across independent GL/Metal/video controls."""
import os
from pathlib import Path
import shlex,subprocess,tempfile
from test_patch_dispatch import method
ROOT=Path(__file__).resolve().parents[1]
SHIM=r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <initializer_list>
#include <VDATableSelection.hpp>
#include <MediaSafetyPolicy.hpp>
bool safetyOption=false;bool checkKernelArgument(const char*){return safetyOption;}
char osversion[32]="24H232";
using UInt32=uint32_t;using UInt64=uint64_t;using UInt8=uint8_t;
#define SYSLOG(...) do{}while(0)
#define DBGLOG(...) do{}while(0)
#define SYSLOG_COND(condition,...) do{assert(!(condition));}while(0)
#define arrsize(a) (sizeof(a)/sizeof((a)[0]))
struct Version {UInt32 v=23;UInt32 major()const{return v;}bool operator>=(const Version&b)const{return v>=b.v;}};
Version version;Version currentKernelVersion(){return version;}const Version MACOS_11{20};
struct KernelPatcher{};
struct DeviceProfile {
 static constexpr unsigned kVcn2_2=514;
 struct {bool conditionalDualQuad=true;}graphics;
 struct {bool hasVCN0=true;unsigned vcnGeneration=kVcn2_2;}media;
 const char* name="test";int family=0,level=0;
 static const char* familyName(int){return "test";}static const char* levelName(int){return "test";}
 static const DeviceProfile* current(){static DeviceProfile p;return &p;}
};
struct NRed {static NRed& singleton(){static NRed n;return n;}bool hasExternalVideo()const{return false;}
 unsigned getDeviceID()const{return 0x1636;}void setProp32(const char*,unsigned){}};
struct UserOpenGL {static inline unsigned inits=0;static void init(unsigned,unsigned,bool,bool){++inits;}};
class UserPatches {
public:
 struct PagePatch {bool glDriver=false,exactOnly=false;};
 static constexpr unsigned kMaxNativePatches=64;
 bool submitGuardEnabled=true,legacyBlendEnabled=true,enabled=true,vdaEnabled=false,vdaResolverEnabled=false;
 bool mediaSafetyEnabled=false;
 bool resolverEnabled=true,resolverOnly=false,semanticEnabled=true,semanticMTLEnabled=true,pageLocalGL=false;
 const int* signatures=nullptr;unsigned signatureCount=0;
 const PagePatch* patches=nullptr;unsigned patchCount=0,nativePatchCount=0;
 bool nativePatchIsVDA[64]{};PagePatch nativePatches[64];
 struct Table{const PagePatch* table;unsigned count;const char* build=nullptr;};Table vdaTables[4];unsigned vdaTableCount=0;
 unsigned nativeHooks=0,cacheHooks=0;
 void installSubmitGuard(KernelPatcher&){++cacheHooks;}
 bool installNativePagePatcher(KernelPatcher&){++nativeHooks;return true;}
 bool installUserPatcher(){assert(false);return false;}
 void selectPatchSet(){static PagePatch p[]={{true,false},{true,false},{false,false}};patches=p;patchCount=3;}
 void processPatcher(KernelPatcher&);
};
const UserPatches::PagePatch kVAEncodePitchPatches_Sequoia[]={{false,true}};
'''
CASES=r'''
int main(){KernelPatcher k;unsigned cases=0;
 for(unsigned major : {22,23,24,25})for(bool gl : {false,true})for(bool blend : {false,true})
 for(bool submit : {false,true})for(bool video : {false,true}){
  version.v=major;UserPatches p;p.enabled=gl;p.legacyBlendEnabled=blend;p.submitGuardEnabled=submit;
  p.vdaEnabled=video;UserOpenGL::inits=0;
  static UserPatches::PagePatch vp[]={{false,true}};p.vdaTables[0]={vp,1};p.vdaTableCount=video?1:0;
  p.processPatcher(k);
  assert(p.cacheHooks==((blend||submit)?1:0));
  assert(p.nativeHooks==((gl||video)?1:0));
  assert(UserOpenGL::inits==((gl&&major>=23)?1:0));
  if(gl&&major>=23&&!video&&!blend)assert(p.nativePatchCount==0&&p.nativeHooks==1);
  ++cases;
 }
 // A target build selects both matching tables and excludes defaults without
 // increasing page capacity. Unknown/empty builds retain the previous fallback.
 for(const char* build : {"24H232","24H32","24H232x",""}) {
  std::strcpy(osversion,build);version.v=24;UserPatches p;p.enabled=false;p.vdaEnabled=true;
  static UserPatches::PagePatch fallback[]={{false,true}};
  static UserPatches::PagePatch target1[]={{false,true},{false,true}},target2[]={{false,true}};
  p.vdaTables[0]={fallback,1,nullptr};p.vdaTables[1]={target1,2,"24H232"};p.vdaTables[2]={target2,1,"24H232"};p.vdaTableCount=3;
  p.processPatcher(k);assert(p.nativePatchCount==(!std::strcmp(build,"24H232")?3:1));
 }
 safetyOption=true;std::strcpy(osversion,"24H232");version.v=24;
 {UserPatches p;p.enabled=false;p.submitGuardEnabled=p.legacyBlendEnabled=false;p.vdaEnabled=true;
  static UserPatches::PagePatch vp[]={{false,true}};p.vdaTables[0]={vp,1,nullptr};p.vdaTableCount=1;
  p.processPatcher(k);assert(p.mediaSafetyEnabled&&p.cacheHooks==1&&p.nativeHooks==0&&!p.nativePatchCount&&!p.vdaResolverEnabled);}
 std::strcpy(osversion,"24H32");
 {UserPatches p;p.enabled=false;p.vdaEnabled=true;static UserPatches::PagePatch vp[]={{false,true}};p.vdaTables[0]={vp,1,nullptr};p.vdaTableCount=1;
  p.processPatcher(k);assert(!p.mediaSafetyEnabled&&p.nativeHooks==1);}
 printf("production installation: %u GL/blend/submit/video/OS combinations; GL-only zero-table hooks retained\n",cases);
}
'''
def main():
 source=(ROOT/'NootedRed/UserPatches.cpp').read_text()
 with tempfile.TemporaryDirectory(prefix='nred-install-') as t:
  p=Path(t);(p/'test.cpp').write_text(SHIM+method(source,'void UserPatches::processPatcher(')+CASES)
  subprocess.run(shlex.split(os.environ.get('CXX','c++'))+['-std=c++17','-fsanitize=address,undefined','-I'+str(ROOT/'NootedRed'),str(p/'test.cpp'),'-o',str(p/'test')],check=True)
  subprocess.run([str(p/'test')],check=True)
if __name__=='__main__':main()
