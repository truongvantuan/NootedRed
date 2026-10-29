// Exact-build private SRD/scratch transaction; no additional hook or map registry.
#include <SurfaceSafety.hpp>
#include <SurfaceExactPlan.hpp>
#include <VPF/TransactionExecutor.hpp>
#include <NRed.hpp>
#include <IOKit/IOLib.h>
#include <libkern/OSAtomic.h>
#include <sys/proc.h>
namespace SurfaceSafety {
namespace {
UserPrivateMemory::Context memory;
volatile UInt32 halted{0},published{0};
constexpr UInt32 PageCapacity=8;
using Page=UserPrivateMemory::Page;
struct Workspace {
    SurfaceExactPlan::Workspace initial,fresh;
    UserSharedCache::Input initialInput,freshInput;
    UserVideoGuardTypes::Patch active[SurfaceExactPlan::SiteCount];
    UInt8 saved[SurfaceExactPlan::SiteCount][SurfaceExactPlan::MaxBytes];
    Page allPages[PageCapacity],activePages[PageCapacity];
    UInt32 allCount,activePageCount,activeCount;
};
struct Owner {
    Workspace* work;
    Owner():work(IONewZero(Workspace,1)){}
    ~Owner(){if(work)IODelete(work,Workspace,1);}
};
int read(UInt64 address,void* bytes,size_t size){return memory.read(address,bytes,size);}
bool addPages(Page* pages,UInt32& count,UInt64 base,const UserVideoGuardTypes::Patch& site){
    if(!site.size||site.size>SurfaceExactPlan::MaxBytes||base>=UserSharedCache::UserLimit
       ||site.offset>=UserSharedCache::UserLimit-base||site.size>UserSharedCache::UserLimit-base-site.offset)return false;
    const auto address=base+site.offset,last=(address+site.size-1)&~UInt64(4095);
    for(UInt64 p=address&~UInt64(4095);p<=last;p+=4096){
        bool seen=false;for(UInt32 i=0;i<count;++i)if(pages[i].address==p)seen=true;
        if(!seen){if(count==PageCapacity)return false;pages[count++].address=p;}
    }
    return true;
}
bool collect(Workspace& w,UInt64 base){
    for(UInt32 i=0;i<w.initial.count;++i){const auto& p=w.initial.sites[i];
        for(UInt32 j=0;j<i;++j){const auto& old=w.initial.sites[j];
            if(p.offset<old.offset+old.size&&old.offset<p.offset+p.size)return false;}
        if(!addPages(w.allPages,w.allCount,base,p))return false;
        // An existing local/native LegacyBlend gate needs validation, not another
        // COW/write. Its saved state must never be undone by SRD rollback.
        if(!memcmp(p.original,p.patched,p.size))continue;
        if(w.activeCount==SurfaceExactPlan::SiteCount||!addPages(w.activePages,w.activePageCount,base,p))return false;
        memcpy(w.saved[w.activeCount],p.original,p.size);w.active[w.activeCount++]=p;
    }
    return true;
}
void reject(UInt32 code){NRed::singleton().setProp32("NRedSurfaceFixRejected",code);}
void halt(){OSCompareAndSwap(0,1,&halted);NRed::singleton().setProp32("NRedSurfaceFixHalted",1);}
void success(int pid,bool fresh,bool legacyBlend){
    if(OSCompareAndSwap(0,1,&published)){
        NRed::singleton().setProp32("NRedSurfaceFixRevision",1);
        NRed::singleton().setProp32("NRedSrdSharedRevision",1);
        NRed::singleton().setProp32("NRedComputeScratchRevision",1);
    }
    char name[32]{};if(pid>0)proc_name(pid,name,sizeof(name));
    if(!strcmp(name,"WindowServer")){
        NRed::singleton().setProp32("NRedSurfaceFixWindowServerPID",static_cast<UInt32>(pid));
        if(legacyBlend){
            NRed::singleton().setProp32("NRedLegacyBlendWindowServerPID",static_cast<UInt32>(pid));
            NRed::singleton().setProp32("NRedLegacyBlendWindowServerApplied",1);
        }
    }
    if(fresh){static volatile UInt32 count{0};
        NRed::singleton().setProp32("NRedSurfaceFixInstalled",static_cast<UInt32>(OSIncrementAtomic(&count)+1));}
}
}
bool configure(UserPrivateMemory::CopyIn in,UserPrivateMemory::CopyOut out,UserPrivateMemory::Query query){
    return memory.configure(in,out,query);
}
__attribute__((noinline)) Result install(vm_map_t map,UInt64 base,UInt32 device,bool legacyBlend,int pid){
    if(!OSCompareAndSwap(0,0,&halted))return Result::Halted;
    if(!map||!memory.ready()||base<0x10000||base>=UserSharedCache::UserLimit-104)return Result::Rejected;
    Owner owner;if(!owner.work){reject(1);return Result::Rejected;}auto& w=*owner.work;
    w.initialInput.reader=read;
    if(!SurfaceExactPlan::build(w.initialInput,base,device,legacyBlend,w.initial)){reject(2);return Result::Rejected;}
    if(!collect(w,base)){reject(3);return Result::Rejected;}
    UserPrivateMemory::Ops ops{memory,map};
    for(UInt32 i=0;i<w.allCount;++i)if(!ops.check(w.allPages[i])){reject(4);return Result::Rejected;}
    if(w.initial.state==SurfaceExactPlan::State::Installed){success(pid,false,legacyBlend);return Result::Installed;}
    if(!w.activeCount){reject(5);return Result::Rejected;}
    using Transaction=VPF::SharedRegionTransaction<UserPrivateMemory::Ops,UserVideoGuardTypes::Patch,Page,SurfaceExactPlan::MaxBytes>;
    Transaction transaction(ops,base,w.active,w.activeCount,w.saved,w.activePages,w.activePageCount,0);
    const auto result=transaction.commit([&]{
        // Repeat whole-function/reference/extra-identity validation immediately
        // before COW; never substitute an applied marker for current bytes.
        w.freshInput.reader=read;
        return SurfaceExactPlan::build(w.freshInput,base,device,legacyBlend,w.fresh)
            &&SurfaceExactPlan::samePlan(w.initial,w.fresh);
    });
    if(result.status==VPF::TransactionStatus::Installed){success(pid,true,legacyBlend);return Result::Installed;}
    if((result.touched&&!result.rollbackOk)
       ||(result.status==VPF::TransactionStatus::ProtectionFailed&&!result.restoreOk)){
        halt();return Result::Halted;
    }
    reject(6+static_cast<UInt32>(result.status));return Result::Rejected;
}
}
