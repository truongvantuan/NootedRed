# Adapted from steve12311/NootedRed fa08caf2005ba4fc09d4250c33e3340d287ca5d3.
"""验证启动解析的映像路径缓冲、完整目录检查和读取失败拒绝，不访问 GPU。"""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'build/cache-metadata-regression'


def main():
    stub = WORK / 'stubs/IOKit'
    stub.mkdir(parents=True, exist_ok=True)
    (stub / 'IOTypes.h').write_text('#pragma once\n#include <cstdint>\nusing UInt8=uint8_t;using UInt32=uint32_t;using UInt64=uint64_t;\n')
    source = r'''
#include <cassert>
#include <cstdio>
#include <map>
#include <set>
#include <string>
#include <vector>
#include <UserSurface24H232Data.hpp>
static std::map<std::string,unsigned> properties;
#include "user-cache-dynamic.hpp"
static unsigned calls;
static uint64_t unreadable;
static int counted(uint64_t address,void* data,size_t size){
 calls++;
 if(unreadable>=address&&unreadable-address<size)return 1;
 return reader(address,data,size);
}
static void setup(){
 using namespace UserSurface24H232Data;
 cache(ResolverImages,ResolverFunctions);
 blocks[base].resize(0x100000);
 word64(base+0x308,0x100000);word32(base+452,2048);
 for(unsigned i=0;i<2048;i++){
  auto path=base+0x20000+i*256;
  char name[256]{};snprintf(name,sizeof(name),"/unused/image/%u",i);
  if(i<imagePaths.size())snprintf(name,sizeof(name),"%s",imagePaths[i].c_str());
  put(path,name,sizeof(name));
  word64(base+0x1000+i*32,i<imageAddresses.size()?imageAddresses[i]-0x200000:unslid+0x9000000+i*4096);
  word32(base+0x1018+i*32,path-base);
 }
 calls=0;unreadable=0;
}
static bool inspect(bool buffered,unsigned index=0){
 using namespace UserSharedCache;
 Input input{counted,{}};UInt8 scan[Input::ScanSize];if(buffered)input.scanBuffer=scan;
 input.selectImages(base,UserSurface24H232Data::ResolverImages,sizeof(UserSurface24H232Data::ResolverImages)/sizeof(UserSurface24H232Data::ResolverImages[0]));
 Image image;
 auto& ref=UserSurface24H232Data::ResolverImages[index];
 bool ok=imageForCache(input,base,image,ref.path,ref.size);
 if(ok){assert(image.address==imageAddresses[index]);assert(input.tableRead);}
 return ok;
}
int main(){
 unsigned reads[2]{};
 for(unsigned variant=0;variant<2;variant++){setup();assert(inspect(variant));reads[variant]=calls;}
 // 启动时完整检查 2048 项目录，底层读取应至少减少四倍。
 printf("metadata reads %u -> %u\n",reads[0],reads[1]);fflush(stdout);
 assert(reads[1]*4<reads[0]);
 for(bool buffered:{false,true}){
  // 最后一项的重复目标也必须拒绝，不能在找到所需映像后提前结束。
  setup();word32(base+0x1018+2047*32,0x20000);assert(!inspect(buffered));
  setup();word32(base+0x1018+2047*32,0x100000-1);assert(!inspect(buffered));
  setup();unreadable=base+0x20000;assert(!inspect(buffered));
  setup();char wrong='!';put(base+0x20000,&wrong,1);assert(!inspect(buffered));
  setup();assert(inspect(buffered,1));
 }
 // 路径跨越已有窗口末尾时重新读取；乱序路径和元数据末尾也保持相同结果。
 setup();auto& ref=UserSurface24H232Data::ResolverImages[1];
 put(base+0x20ff8,ref.path,ref.size);word32(base+0x1018+32,0x20ff8);
 assert(inspect(true,1));
 for(bool buffered:{false,true}){
  setup();auto& last=UserSurface24H232Data::ResolverImages[0];
  unsigned maxPath=0;for(auto& image:UserSurface24H232Data::ResolverImages)maxPath=std::max(maxPath,image.size);
  put(base+0x100000-maxPath,last.path,last.size);
  word32(base+0x1018,0x100000-maxPath);assert(inspect(buffered));
 }
 // 新调用不能沿用旧路径内容。
 setup();assert(inspect(true));char changed='!';put(base+0x20000,&changed,1);assert(!inspect(true));

 // Metadata parsing inside a text candidate must not overwrite the live buffer.
 // A nested scan uses its bounded local buffer and returns ownership to the outer scan.
 for(bool duplicate:{false,true}){
  setup();using namespace UserSharedCache;
  Input input{counted,{base,0x400000000ULL}};UInt8 scan[Input::ScanSize];input.scanBuffer=scan;
  auto text=Range{imageAddresses[0]+0x1000,0x6f000};unsigned nested=0;
  const auto* prefix=UserSurface24H232Data::ResolverOriginal0;
  const auto nestedAddress=imageAddresses[0]+0x65000;
  put(nestedAddress,prefix,32);
  if(duplicate)put(imageAddresses[0]+0x60000,prefix,32);
  UInt64 found=0;
  auto candidate=[&](UInt64 address){
   if(address==nestedAddress)return false;
   ++nested;assert(input.scanBufferInUse);std::vector<UInt8> snapshot(scan,scan+sizeof(scan));
   UInt64 inner=0;
   assert(UserCacheResolver::scanFunction(input,Range{nestedAddress,64},32,32,
    [&](const UInt8* bytes){return !memcmp(bytes,prefix,32);},[](UInt64){return true;},inner));
   assert(inner==nestedAddress&&input.scanBufferInUse&&!memcmp(snapshot.data(),scan,sizeof(scan)));
   Image image;auto& ref=UserSurface24H232Data::ResolverImages[0];
   assert(imageForCache(input,base,image,ref.path,ref.size));
   assert(input.scanBufferInUse&&!memcmp(snapshot.data(),scan,sizeof(scan)));
   return true;
  };
  const bool ok=UserCacheResolver::scanFunction(input,text,32,32,
   [&](const UInt8* bytes){return !memcmp(bytes,prefix,32);},candidate,found);
  assert(ok==!duplicate&&nested==(duplicate?2U:1U)&&!input.scanBufferInUse);
 }
 puts("PASS metadata: read reduction, full-directory/fault/bounds validation, window edges, nested metadata/scan buffer ownership and ambiguity");
}
'''
    path, executable = WORK / 'test.cpp', WORK / 'test'
    path.write_text(source)
    subprocess.run(['xcrun', 'clang++', '-std=c++23', '-O2', '-fsanitize=address,undefined',
                    '-fno-omit-frame-pointer', '-fno-sanitize-recover=all', '-I' + str(WORK / 'stubs'),
                    '-I' + str(ROOT / 'NootedRed'), '-I' + str(ROOT / 'tools/fixtures'),
                    str(path), '-o', str(executable)], check=True, timeout=60)
    subprocess.run([str(executable)], check=True, timeout=60)


if __name__ == '__main__':
    main()
