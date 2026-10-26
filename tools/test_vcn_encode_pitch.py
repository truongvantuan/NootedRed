#!/usr/bin/env python3
"""Execute the captured Sequoia function and production pitch bytes on CPU-only fake objects."""
from pathlib import Path
import hashlib,os,platform,shlex,subprocess,tempfile
from test_gl_semantic_data import load_arrays
ROOT=Path(__file__).resolve().parents[1]
if platform.machine().lower() not in ('x86_64','amd64'):
    print('SKIP: captured x86_64 function requires an x86_64 CPU');raise SystemExit(0)
a=load_arrays(ROOT/'NootedRed/UserPatches.cpp');page=a['kVAEncodePitchPage_Sequoia']
original=page[0xac4:0xac4+138]
assert hashlib.sha256(original).hexdigest()=='c8193ea2d2c7193012a5618b6918d41fffe30ad0c1389256fee983e66ac24347'
old,new=a['kVAEncodePitchFind'],a['kVAEncodePitchReplace']
assert len(old)==len(new)==37 and original[0x31:0x56]==old and page.count(old)==1
candidate=original[:0x31]+new+original[0x56:]
def array(name,data):return 'const unsigned char '+name+'[]={'+','.join(map(str,data))+'};\n'
source=r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <sys/mman.h>
static std::array<uint32_t,11> result;
static void *expectedProcessor,*expectedInput,*expectedCommand;
static unsigned filled,captured;
static void fill(void *processor,void *input,void *parameters) {
 assert(processor==expectedProcessor && input==expectedInput);filled++;
 auto *p=static_cast<uint32_t*>(parameters);p[0]=0x11223344;p[9]=77;p[10]=88;
}
static void capture(void *command,unsigned kind,const void *parameters) {
 assert(command==expectedCommand && kind==10);captured++;
 memcpy(result.data(),parameters,sizeof(result));
}
template<class T,size_t N> void put(std::array<uint8_t,N>&a,size_t offset,T value) {
 assert(offset+sizeof(value)<=N);memcpy(a.data()+offset,&value,sizeof(value));
}
int main() {
 unsigned char *code=static_cast<unsigned char*>(mmap(nullptr,4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0));assert(code!=MAP_FAILED);
 memcpy(code,stock,sizeof(stock));memcpy(code+512,fixed,sizeof(fixed));assert(mprotect(code,4096,PROT_READ|PROT_EXEC)==0);
 using Function=void(*)(void*,void*,void*);auto old=reinterpret_cast<Function>(code);auto fix=reinterpret_cast<Function>(code+512);
 std::array<uint8_t,0x500> encoder{};std::array<uint8_t,0x88> texture{};
 std::array<uintptr_t,24> processorTable{},commandTable{};
 processorTable[0xb0/8]=reinterpret_cast<uintptr_t>(fill);commandTable[0x70/8]=reinterpret_cast<uintptr_t>(capture);
 uintptr_t *processor=processorTable.data(),*command=commandTable.data();
 expectedProcessor=&processor;expectedCommand=&command;expectedInput=texture.data()+1;
 put(encoder,0x2f8,&processor);put(encoder,0x458,&command);put(encoder,0x210,uint32_t{0x151800});
 unsigned cases=0,different=0;
 for(uint32_t width:{16,640,1280,1920,3840})for(uint32_t element:{1,2,4})for(uint32_t alignment:{256,2048,4096}){
  uint32_t stride=(width*element+alignment-1)&~(alignment-1);
  put(encoder,0x424,width);put(texture,0x80,stride);put(texture,0x84,element);
  auto savedEncoder=encoder;auto savedTexture=texture;
  old(encoder.data(),expectedInput,texture.data());auto before=result;
  assert(before[6]==((width*element+255)&~255U)/element && before[7]==before[6]/2);
  fix(encoder.data(),expectedInput,texture.data());
  assert(result[6]==stride/element && result[7]==stride/element/2);
  for(size_t i=0;i<result.size();i++)if(i!=6 && i!=7)assert(before[i]==result[i]);
  assert(encoder==savedEncoder && texture==savedTexture);
  if(before[6]!=result[6])different++;
  cases++;
 }
 assert(cases==45 && different>0 && filled==2*cases && captured==2*cases);
 printf("PASS %u native CPU pitch cases (%u reproduce the width/stride mismatch); both callbacks, other parameters and input objects preserved.\n",cases,different);
 munmap(code,4096);
}
'''
with tempfile.TemporaryDirectory(prefix='nred-vcn-pitch-') as d:
    d=Path(d);cpp=d/'pitch.cpp';binary=d/'pitch'
    cpp.write_text(array('stock',original)+array('fixed',candidate)+source)
    subprocess.run(shlex.split(os.environ.get('CXX','c++'))+['-std=c++17','-O1','-g','-Wall','-Wextra','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(cpp),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
