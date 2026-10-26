#!/usr/bin/env python3
"""Execute production GL budget bytes and the captured native add-resource routine on CPU fixtures.

No Apple driver function is called: the copied add routine's three external calls are
rebound to CPU stubs. The exact native instructions reproduce the 512 MB rejection.
"""
from pathlib import Path
import os,platform,shlex,subprocess,tempfile
from test_gl_semantic_data import load_arrays
ROOT=Path(__file__).resolve().parents[1]
if platform.machine().lower() not in ('x86_64','amd64'):
    print('SKIP: native x86_64 instruction execution requires an x86_64 host')
    raise SystemExit(0)
arrays=load_arrays(ROOT/'NootedRed/UserPatches.cpp')
PREFIX=r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <stddef.h>
#include <string.h>
#include <sys/mman.h>
#include <assert.h>
#include <unistd.h>
typedef struct {uint16_t count,capacity;uint32_t pad;uint32_t *ids;void *context;void **handles;uint32_t budget_kib,used_kib;} List;
typedef struct {unsigned char shared[320],client[64];uint64_t size;unsigned retain_count;} Resource;
_Static_assert(sizeof(List)==40&&offsetof(List,budget_kib)==32,"native layout");
static void *get_shared(Resource*r,void**out){*out=r->client;return r->shared;}
static uint64_t resident_size(Resource*r){return r->size;}
static void *retain_resource(Resource*r){r->retain_count++;return r;}
'''
SUFFIX=r'''static void patch_call(unsigned char *func,size_t offset,unsigned char *stub,void *target){
 assert(func[offset]==0xe8);int32_t rel=(int32_t)(stub-(func+offset+5));memcpy(func+offset+1,&rel,4);
 const unsigned char jump[]={0xff,0x25,0,0,0,0};memcpy(stub,jump,6);memcpy(stub+6,&target,8);
}
typedef void (*Init)(List*,void*);
typedef unsigned (*Add)(List*,Resource*,unsigned);
static void *context(uint32_t mb,unsigned char *ctx,unsigned char *hw){memset(ctx,0,0x12e0);memset(hw,0,192);memcpy(hw+20,&mb,4);void*p=hw;memcpy(ctx+0x12d8,&p,8);return ctx;}
static void prepare(List*l,Init init,uint32_t mb,unsigned char *ctx,unsigned char *hw,uint32_t*ids,void**handles){
 memset(l,0xcc,sizeof(*l));init(l,context(mb,ctx,hw));l->capacity=8;l->ids=ids;l->handles=handles;
 memset(ids,0,32);memset(handles,0,64);
}
int main(void){
 unsigned char*code=mmap(NULL,16384,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);assert(code!=MAP_FAILED);
 memcpy(code+256,stock,sizeof(stock));memcpy(code+512,fixed,sizeof(fixed));memcpy(code+4096+256,add_resource,sizeof(add_resource));
 unsigned char*a=code+4096+256;
 patch_call(a,0x58cb-0x58aa,code+8192,(void*)get_shared);
 patch_call(a,0x58da-0x58aa,code+8224,(void*)resident_size);
 patch_call(a,0x5958-0x58aa,code+8256,(void*)retain_resource);
 assert(mprotect(code,16384,PROT_READ|PROT_EXEC)==0);
 Init old=(Init)(void*)(code+256),fix=(Init)(void*)(code+512);Add add=(Add)(void*)a;
 unsigned char ctx[0x12e0],hw[192];uint32_t sizes[]={0,256,511,512,513,1024,2048,4096,16384,UINT32_MAX};
 for(unsigned i=0;i<sizeof(sizes)/sizeof(sizes[0]);i++){
  struct {uint64_t before;List l;uint64_t after;} x,y;
  memset(&x,0xcc,sizeof(x));memset(&y,0xcc,sizeof(y));
  old(&x.l,context(sizes[i],ctx,hw));fix(&y.l,ctx);
  uint32_t expected=(sizes[i]<<10)-0x80000U;
  assert(x.l.budget_kib==expected&&y.l.budget_kib==(expected?expected:0x40000U));
  y.l.budget_kib=x.l.budget_kib;assert(memcmp(&x,&y,sizeof(x))==0);
 }
 uint32_t ids[8];void*handles[8];List l;Resource r={0};r.size=4096;uint32_t id=77;memcpy(r.shared+0x100,&id,4);
 prepare(&l,old,512,ctx,hw,ids,handles);assert(l.budget_kib==0);
 assert(add(&l,&r,0)==0xffff&&l.count==0&&r.retain_count==0);
 prepare(&l,fix,512,ctx,hw,ids,handles);assert(l.budget_kib==0x40000);
 assert(add(&l,&r,0)==0&&l.count==1&&l.used_kib==4&&r.retain_count==1&&ids[0]==77&&handles[0]==&r);
 uint32_t refs;memcpy(&refs,r.client+24,4);assert(refs==1);
 assert(add(&l,&r,1)==0&&l.count==1&&ids[0]==(77U|0x80000000U)&&r.retain_count==1);
 Resource huge={0};huge.size=257ULL<<20;id=78;memcpy(huge.shared+0x100,&id,4);
 assert(add(&l,&huge,0)==0xffff&&l.count==1&&huge.retain_count==0);
 prepare(&l,fix,512,ctx,hw,ids,handles);l.capacity=0;r.retain_count=0;
 assert(add(&l,&r,0)==0xffff&&l.count==0&&r.retain_count==0);
 puts("Stock 512 MB budget=0 rejects 4 KB; corrected budget=256 MB accepts and retains it; other budgets, dirty refs, capacity and bounds preserved. CPU only.");
 munmap(code,16384);return 0;
}
'''
ADD_RESOURCE=bytes.fromhex('554889e54157415641554154534883ec188955d44989f64889fb488d75c84c89f7e864760e00448ba0000100004c89f7e867760e004989c7440fb72b4d85ed741e488b4b0831c08b148189d681e6ffffff7f4439e6746848ffc04939c575e849c1ef0a8b4b208b53244c01fa66b8ffff4839ca775966443b6b027352488b4308468924a8837dd400740e488b43080fb70b810c8800000080488b43180fb70b4c8934c8488b45c8f0ff40184c89f7e877750e0066ff0344017b244489e8eb0f837dd400740981ca000000808914810fb7c04883c4185b415c415d415e415f5dc3')

def array(name,data):return 'static const unsigned char '+name+'[]={'+','.join(hex(v) for v in data)+'};\n'
with tempfile.TemporaryDirectory(prefix='nred-gl-budget-') as directory:
    cpp=Path(directory)/'budget.c';binary=Path(directory)/'budget'
    cpp.write_text(PREFIX+array('stock',arrays['kGLDriverBudgetFind'])+
                   array('fixed',arrays['kGLDriverBudgetReplace'])+array('add_resource',ADD_RESOURCE)+SUFFIX)
    subprocess.run(shlex.split(os.environ.get('CC','cc'))+['-std=c11','-O1','-g',
        '-fsanitize=address,undefined','-fno-omit-frame-pointer',str(cpp),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
