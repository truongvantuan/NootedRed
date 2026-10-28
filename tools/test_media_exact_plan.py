#!/usr/bin/env python3
"""Execute the exact media planner with real reference pages and fault injection; no GPU."""
from pathlib import Path
import subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
SOURCE=r'''
#include <cassert>
#include <map>
#include <vector>
#include <cstring>
#include <cstdio>
#include <MediaReference24H232.hpp>
using namespace MediaExactPlan;
constexpr UInt64 base=0x7ff800000000ULL;
struct Input {
 std::map<UInt64,std::vector<UInt8>> pages;bool fail=false;
 bool read(UInt64 a,void* out,unsigned n){auto it=pages.find(a-base);if(fail||it==pages.end()||n!=4096)return false;memcpy(out,it->second.data(),n);return true;}
};
int main(){Input in;Workspace w;
 auto reset=[&]{in={};for(auto& p:MediaReference24H232::Pages)in.pages[p.offset]={p.bytes,p.bytes+4096};};
 auto build=[&]{return MediaExactPlan::build(in,base,MediaReference24H232::Pages,10,
  VDAVADataSequoia24H232::Patches,VDAVADataSequoia24H232::PatchCount,
  VDAGVADataSequoia24H232::Patches,1,w);};
 auto apply=[&]{for(unsigned i=0;i<w.count;++i){auto& p=w.sites[i];auto key=p.offset&~UInt64(4095);memcpy(in.pages[key].data()+(p.offset&4095),p.patched,p.size);}};
 reset();assert(build()&&w.state==State::Original&&w.count==14);auto original=in.pages;
 apply();assert(build()&&w.state==State::Patched&&w.count==14);auto patched=in.pages;
 for(auto& p:MediaReference24H232::Pages){
  for(unsigned off:{0U,127U,2048U,4095U}){in.pages=original;in.pages[p.offset][off]^=0x80;assert(!build()&&w.state==State::Rejected);}
  in.pages=original;in.pages[p.offset]=patched[p.offset];assert(!build()&&w.state==State::Mixed);
  in.pages=patched;in.pages.erase(p.offset);assert(!build()&&w.state==State::Rejected);
 }
 reset();in.fail=true;assert(!build());
 reset();auto va=VDAVADataSequoia24H232::Patches[0];va.size=65;
 assert(!MediaExactPlan::build(in,base,MediaReference24H232::Pages,10,&va,1,VDAGVADataSequoia24H232::Patches,1,w));
 auto bad=MediaReference24H232::Pages[0];bad.offset|=1;
 assert(!MediaExactPlan::build(in,base,&bad,1,VDAVADataSequoia24H232::Patches,10,VDAGVADataSequoia24H232::Patches,1,w));
 reset();assert(build());for(unsigned i=0;i<w.count;++i)for(unsigned j=0;j<i;++j){auto&a=w.sites[i];auto&b=w.sites[j];assert(!(a.offset<b.offset+b.size&&b.offset<a.offset+a.size));}
 puts("PASS exact media planner: 10 complete pages, 14 sites, stock/patched/mixed, every page corrupt/missing, read/size/alignment failures and non-overlap");
}
'''
def main():
 with tempfile.TemporaryDirectory(prefix='nred-media-plan-') as d:
  p=Path(d);(p/'IOKit').mkdir();(p/'libkern').mkdir()
  types='#pragma once\n#include <cstdint>\nusing UInt8=uint8_t;using UInt32=uint32_t;using UInt64=uint64_t;\n'
  (p/'IOKit/IOTypes.h').write_text(types);(p/'libkern/OSTypes.h').write_text(types)
  (p/'UserPatches.hpp').write_text('#pragma once\n#include <cstddef>\n#include <IOKit/IOTypes.h>\nnamespace UserPatcher{enum class FileSegment{SegmentTextText};}\nstruct UserPatches{struct PagePatch{UserPatcher::FileSegment segment;const UInt8*page;const UInt8*find;const UInt8*replace;size_t size,skip,count;bool glDriver=false,exactOnly=false;};};\n')
  (p/'test.cpp').write_text(SOURCE)
  subprocess.run(['xcrun','clang++','-std=c++23','-O2','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(p),'-I'+str(ROOT/'NootedRed'),str(p/'test.cpp'),'-o',str(p/'test')],check=True,timeout=60)
  subprocess.run([str(p/'test')],check=True,timeout=30)
if __name__=='__main__':main()
