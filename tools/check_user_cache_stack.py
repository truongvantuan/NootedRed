#!/usr/bin/env python3
"""Measure the shared-cache hook's visible stack using its actual xmake compile flags.

External native syscall, VM, IOKit, copyin/out and lock frames are excluded.
This does not measure the whole kernel stack or bound arbitrary indirect calls.
"""
import argparse,json,re,shlex,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--compile-log',type=Path,required=True)
 p.add_argument('--out',type=Path,required=True)
 a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
 text=re.sub(r'\x1b\[[0-9;]*m','',a.compile_log.read_text())
 command=next(shlex.split(line) for line in text.splitlines() if line.startswith('/') and 'clang++ -c ' in line and line.endswith('NootedRed/UserPatches.cpp'))
 pos=command.index('-o');del command[pos:pos+2];command.remove('-c');command.remove('NootedRed/UserPatches.cpp')
 obj=a.out/'UserPatches.o';ir=a.out/'UserPatches.ll'
 commands=[command+['-c','-fstack-usage','NootedRed/UserPatches.cpp','-o',str(obj)],command+['-S','-emit-llvm','NootedRed/UserPatches.cpp','-o',str(ir)]]
 for command in commands:
  with (a.out/'compile.log').open('a') as log:subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=90)
 frames={}
 for line in obj.with_suffix('.su').read_text().splitlines():
  name,size,kind=line.split('\t');frames[name.rsplit(':',1)[-1]]=(int(size),kind)
 edges={};current=None
 def symbols(line):return [a or b for a,b in re.findall(r'@(?:"([^"]+)"|([^\s(]+))\(',line)]
 for line in ir.read_text().splitlines():
  if line.startswith('define '):current=symbols(line)[0];edges[current]=set()
  elif line=='}':current=None
  elif current and re.search(r'\b(call|invoke)\b',line):edges[current].update(symbols(line))
 def longest(name,parents=frozenset()):
  if name in parents:raise AssertionError('Recursive internal call chain: '+name)
  size,kind=frames[name];assert kind=='static',(name,kind)
  children=[longest(child,parents|{name}) for child in edges.get(name,[]) if child in frames]
  best=max(children,key=lambda x:x[0],default=(0,[]))
  return size+best[0],[{'symbol':name,'bytes':size}]+best[1]
 roots=[n for n in frames if 'wrapSharedRegionCheck' in n];assert len(roots)==1,roots
 total,path=longest(roots[0]);reachable=set()
 def visit(name):
  if name in reachable:return
  reachable.add(name)
  for child in edges.get(name,[]):
   if child in frames:visit(child)
 visit(roots[0]);largest=max(frames[n][0] for n in reachable)
 report={'wrapper_bytes':frames[roots[0]][0],'maximum_reachable_frame_bytes':largest,'visible_direct_chain_bytes':total,'chain':path,'limits':{'wrapper':512,'frame':2048,'chain':8192},'commands':commands,'scope':'RELEASE production flags; shared-cache wrapper and visible direct internal calls only; excludes native syscall, VM/IOKit/lock implementations and indirect callbacks. Not a whole kernel-stack bound.'}
 (a.out/'REPORT.json').write_text(json.dumps(report,indent=2)+'\n')
 assert report['wrapper_bytes']<=512 and largest<=2048 and total<=8192,report
 print(json.dumps({k:v for k,v in report.items() if k not in ['commands','chain']},indent=2))
if __name__=='__main__':main()
