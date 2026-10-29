// Private guard-first media transaction. No additional syscall or pager hook.
#include <MediaSafety.hpp>
#include <MediaReference24H232.hpp>
#include <UserVideoGuardResolver.hpp>
#include <VPF/TransactionExecutor.hpp>
#include <NRed.hpp>
#include <IOKit/IOLib.h>
#include <libkern/OSAtomic.h>
#include <sys/proc.h>
namespace MediaSafety {
namespace {
UserPrivateMemory::Context memory;
using Page=UserPrivateMemory::Page;
using Ops=UserPrivateMemory::Ops;
volatile UInt32 halted{0},published{0};
constexpr UInt32 Capacity=32,PageCapacity=32,PatchBytes=64;
struct Workspace {
    UserVideoGuardResolver::Plan guard;
    MediaExactPlan::Workspace media;
    UserSharedCache::Input input;
    UInt8 scan[UserSharedCache::Input::ScanSize];
    UserVideoGuardTypes::Patch combined[Capacity];
    UInt8 saved[Capacity][PatchBytes];
    Page pages[PageCapacity];
    UInt32 count,pageCount;
    vm_address_t allocation;
    bool retained;
};
int read(UInt64 address,void* bytes,size_t size){return memory.read(address,bytes,size);}
bool payloadRX(vm_map_t map,UInt64 page){return UserPrivateMemory::payloadRX(memory,map,page);}
struct Owner {
    Workspace* work;vm_map_t map;
    Owner(vm_map_t map):work(IONewZero(Workspace,1)),map(map){}
    ~Owner(){if(!work)return;
        if(work->allocation&&!work->retained)vm_deallocate(map,work->allocation,4096);
        IODelete(work,Workspace,1);
    }
};
bool collect(Workspace& w,UInt64 base) {
    for(UInt32 i=0;i<w.count;++i){
        const auto& s=w.combined[i];
        if(!s.size||s.size>PatchBytes||s.offset>=UserSharedCache::UserLimit-base
           ||s.size>UserSharedCache::UserLimit-base-s.offset)return false;
        const UInt64 address=base+s.offset,last=(address+s.size-1)&~UInt64(4095);
        for(UInt64 p=address&~UInt64(4095);p<=last;p+=4096){
            bool seen=false;for(UInt32 j=0;j<w.pageCount;++j)if(w.pages[j].address==p)seen=true;
            if(!seen){if(w.pageCount==PageCapacity)return false;w.pages[w.pageCount++].address=p;}
        }
        for(UInt32 j=0;j<i;++j){const auto& prev=w.combined[j];
            if(s.offset<prev.offset+prev.size&&prev.offset<s.offset+s.size)return false;}
        memcpy(w.saved[i],s.original,s.size);
    }
    return true;
}
bool mediaPlan(Workspace& w,UInt64 base){
    return MediaExactPlan::build(w.input,base,MediaReference24H232::Pages,10,
        VDAVADataSequoia24H232::Patches,VDAVADataSequoia24H232::PatchCount,
        VDAGVADataSequoia24H232::Patches,1,w.media);
}
void reject(UInt32 code){NRed::singleton().setProp32("NRedVCNSafetyRejected",code);}
void halt(){OSCompareAndSwap(0,1,&halted);NRed::singleton().setProp32("NRedVCNSafetyHalted",1);}
void success(int pid,bool fresh){
    if(OSCompareAndSwap(0,1,&published)){
        NRed::singleton().setProp32("NRedVCNEncodeGuardRevision",1);
        NRed::singleton().setProp32("NRedVCNDecodeGuardRevision",1);
        NRed::singleton().setProp32("NRedVCNSafetyMediaRevision",1);
    }
    char name[32]{};if(pid>0)proc_name(pid,name,sizeof(name));
    if(strncmp(name,"VTEncoderXPC",12)==0)NRed::singleton().setProp32("NRedVCNGuardedEncoderPID",static_cast<UInt32>(pid));
    if(strncmp(name,"VTDecoderXPC",12)==0)NRed::singleton().setProp32("NRedVCNGuardedDecoderPID",static_cast<UInt32>(pid));
    if(fresh){static volatile UInt32 count{0};
        NRed::singleton().setProp32("NRedVCNSafetyInstalled",static_cast<UInt32>(OSIncrementAtomic(&count)+1));}
}
}
bool configure(CopyIn in,CopyOut out,Query query){return memory.configure(in,out,query);}
__attribute__((noinline)) void install(vm_map_t map,UInt64 base,int pid){
    if(!map||!memory.ready()||!OSCompareAndSwap(0,0,&halted)
       ||base<0x10000||base>=UserSharedCache::UserLimit-104)return;
    UInt8 header[104]{};
    static constexpr UInt8 uuid[]={0x90,0xdb,0x0d,0xeb,0x23,0x44,0x36,0x01,0xb0,0x11,0xb8,0x73,0x12,0xd7,0x4c,0xfb};
    if(read(base,header,sizeof(header))||memcmp(header,"dyld_v1 x86_64h",16)||memcmp(header+88,uuid,16))return;
    Owner owner(map);if(!owner.work){reject(1);return;}auto& w=*owner.work;
    w.input.reader=read;w.input.scanBuffer=w.scan;
    if(!UserVideoGuardResolver::resolve(w.input,base,24,w.guard)){reject(2);return;}
    if(!mediaPlan(w,base)){reject(3);return;}
    if(w.guard.installed){
        if(w.media.state!=MediaExactPlan::State::Patched||!payloadRX(map,w.guard.page)){reject(4);return;}
        for(UInt32 i=0;i<w.guard.count;++i)w.combined[w.count++]=w.guard.patches[i];
        for(UInt32 i=0;i<w.media.count;++i)w.combined[w.count++]=w.media.sites[i];
        if(!collect(w,base)){reject(4);return;}Ops ops{memory,map};
        for(UInt32 i=0;i<w.pageCount;++i)if(!ops.check(w.pages[i])){reject(4);return;}
        success(pid,false);return;
    }
    if(w.media.state!=MediaExactPlan::State::Original){reject(5);return;}
    const UInt32 prefix=w.guard.count;
    if(prefix!=4||prefix+w.media.count>Capacity){reject(5);return;}
    for(UInt32 i=0;i<prefix;++i)w.combined[w.count++]=w.guard.patches[i];
    for(UInt32 i=0;i<w.media.count;++i)w.combined[w.count++]=w.media.sites[i];
    if(!collect(w,base)){reject(5);return;}Ops ops{memory,map};
    using Transaction=VPF::SharedRegionTransaction<Ops,UserVideoGuardTypes::Patch,Page,PatchBytes>;
    Transaction transaction(ops,base,w.combined,w.count,w.saved,w.pages,w.pageCount,prefix);
    const auto result=transaction.commit([&]{
        if(vm_allocate(map,&w.allocation,4096,VM_FLAGS_ANYWHERE)!=KERN_SUCCESS)return false;
        if(!UserVideoGuardResolver::setPage(w.guard,w.allocation,24))return false;
        if(memory.write(w.guard.expected,w.allocation,w.guard.length))return false;
        if(vm_protect(map,w.allocation,4096,FALSE,VM_PROT_READ|VM_PROT_EXECUTE)!=KERN_SUCCESS
           ||vm_protect(map,w.allocation,4096,TRUE,VM_PROT_READ|VM_PROT_EXECUTE)!=KERN_SUCCESS
           ||!payloadRX(map,w.allocation))return false;
        if(read(w.allocation,w.guard.observed,w.guard.length)||memcmp(w.guard.expected,w.guard.observed,w.guard.length))return false;
        // Recheck every original media page immediately before code-page COW.
        // Entry-only checks would miss unrelated changes since initial planning.
        for(const auto& page:MediaReference24H232::Pages){
            if(read(base+page.offset,w.media.observed,4096)
               ||memcmp(w.media.observed,page.bytes,4096))return false;
        }
        // Pointers into guard.patched remain live after binding the private page.
        UInt8 bytes[PatchBytes];
        for(UInt32 i=0;i<w.count;++i){const auto& s=w.combined[i];
            if(read(base+s.offset,bytes,s.size)||memcmp(bytes,w.saved[i],s.size))return false;}
        return true;
    });
    if(result.status==VPF::TransactionStatus::Installed){w.retained=true;success(pid,true);return;}
    if(result.touched&&!result.rollbackOk){w.retained=true;halt();}
    if(result.status==VPF::TransactionStatus::ProtectionFailed&&!result.restoreOk)halt();
    reject(6+static_cast<UInt32>(result.status));
}
}
