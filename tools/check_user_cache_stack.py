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
 p.add_argument('--media-adapter',action='store_true',help='Include the private media adapter translation unit and direct calls across it')
 a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
 text=re.sub(r'\x1b\[[0-9;]*m','',a.compile_log.read_text())
 candidates=[shlex.split(line) for line in text.splitlines() if line.startswith('/') and 'clang++ -c ' in line
             and line.endswith(('NootedRed/UserPatches.cpp','NootedRed/MediaSafety.cpp'))]
 if not candidates:raise SystemExit('No UserPatches/MediaSafety compile command in supplied log')
 command=candidates[0]
 pos=command.index('-o');del command[pos:pos+2];command.remove('-c');command.pop() # source
 sources=['UserPatches']+(['MediaSafety'] if a.media_adapter else [])
 commands=[];frames={};edges={}
 def symbols(line):return [a or b for a,b in re.findall(r'@(?:"([^"]+)"|([^\s(]+))\(',line)]
 for source in sources:
  obj=a.out/(source+'.o');ir=a.out/(source+'.ll');path='NootedRed/'+source+'.cpp'
  steps=[command+['-c','-fstack-usage',path,'-o',str(obj)],command+['-S','-emit-llvm',path,'-o',str(ir)]]
  commands.extend(steps)
  for step in steps:
   with (a.out/'compile.log').open('a') as log:subprocess.run(step,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=90)
  for line in obj.with_suffix('.su').read_text().splitlines():
   name,size,kind=line.split('\t');name=name.rsplit(':',1)[-1]
   assert kind=='static',(name,kind)
   # Inline/template definitions can be emitted by both units. Keep the larger frame.
   frames[name]=max(frames.get(name,(0,'static')),(int(size),kind))
  current=None
  for line in ir.read_text().splitlines():
   if line.startswith('define '):current=symbols(line)[0];edges.setdefault(current,set())
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
