#!/usr/bin/env python3
"""Reproduce old startup schedules; exercise the candidate gate without kernel work."""
import itertools
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CPP = r'''
#include <cassert>
#include <atomic>
#include <thread>
#include "kern_startup.hpp"
int main() {
 // Exhaust all notification strings through length eight, including duplicates.
 for(unsigned length=1;length<=8;++length)for(unsigned bits=0;bits<(1U<<length);++bits){
  _Atomic(uint32_t) state=0;unsigned publications=0,seen=0;
  for(unsigned i=0;i<length;++i){unsigned flag=(bits&(1U<<i))?1:2;seen|=flag;publications+=VSMCStartup::arrive(&state,flag);}
  assert(publications==(seen==3?1U:0U));
 }
 // First-generation service initialization needs no MMIO callback.
 for(unsigned order=0;order<2;++order){
  _Atomic(uint32_t) state=0;unsigned count=0;
  count+=VSMCStartup::arrive(&state,order?3:2);
  count+=VSMCStartup::arrive(&state,order?2:3);
  for(unsigned i=0;i<8;++i)count+=VSMCStartup::arrive(&state,3);
  assert(count==1);
 }
 for(unsigned trial=0;trial<2000;++trial){
  _Atomic(uint32_t) state=0;int payload[2]={0,0};
  std::atomic<unsigned> ready{0},published{0};std::atomic<bool> go{false};
  auto producer=[&](unsigned index){
   ready.fetch_add(1);while(!go.load(std::memory_order_acquire))std::this_thread::yield();
   payload[index]=int(index+17);
   for(unsigned duplicate=0;duplicate<3;++duplicate)
    if(VSMCStartup::arrive(&state,1U<<index)){
     assert(payload[0]==17&&payload[1]==18);published.fetch_add(1);
    }
  };
  std::thread a(producer,0),b(producer,1);
  while(ready.load()!=2)std::this_thread::yield();go.store(true,std::memory_order_release);
  a.join();b.join();assert(published.load()==1);
 }
}
'''


def main():
    counts = []
    for order in itertools.permutations(['A-store','A-read','B-read','B-store']):
        if order.index('A-store') > order.index('A-read') or order.index('B-read') > order.index('B-store'):
            continue
        servicing = mmio = cached = False
        published = 0
        for op in order:
            if op == 'A-store': servicing = True
            elif op == 'A-read': published += int(mmio)
            elif op == 'B-read': cached = servicing
            else: mmio = True; published += int(cached)
        counts.append(published)
    assert sorted(counts) == [0,1,1,1,1,2]
    print('Old source ordering: 6 legal schedules, including one missed and one duplicate publication', flush=True)
    with tempfile.TemporaryDirectory(prefix='vsmc-startup-') as directory:
        root = Path(directory); (root/'test.cpp').write_text(CPP)
        subprocess.run(['xcrun','clang++','-std=c++17','-O1','-pthread','-fsanitize=thread',
                        '-I'+str(ROOT/'tools/patches/virtualsmc'),str(root/'test.cpp'),'-o',str(root/'test')],check=True)
        subprocess.run([str(root/'test')],check=True)
    print('Candidate: all notification strings through length 8, legacy mode, 2000 concurrent starts and payload publication passed under ThreadSanitizer')


if __name__ == '__main__':
    main()
