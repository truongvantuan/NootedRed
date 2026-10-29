// Shared VM permissions and copy callbacks for private user-cache transactions.
#pragma once
#include <IOKit/IOTypes.h>
#include <mach/vm_map.h>
#include <mach/vm_region.h>
namespace UserPrivateMemory {
using CopyIn=int (*)(const void*,void*,size_t);
using CopyOut=int (*)(const void*,void*,size_t);
using Query=kern_return_t (*)(vm_map_t,mach_vm_address_t*,mach_vm_size_t*,natural_t*,vm_region_recurse_info_t,mach_msg_type_number_t*);
constexpr UInt32 PageSize=4096;
struct Context {
    CopyIn in{nullptr};CopyOut out{nullptr};Query query{nullptr};
    bool ready() const {return in&&out&&query;}
    bool configure(CopyIn read,CopyOut write,Query region) {
        if(!read||!write||!region||(in&&(in!=read||out!=write||query!=region)))return false;
        in=read;out=write;query=region;return true;
    }
    int read(UInt64 address,void* bytes,size_t size) const {return in(reinterpret_cast<const void*>(address),bytes,size);}
    int write(const void* bytes,UInt64 address,size_t size) const {return out(bytes,reinterpret_cast<void*>(address),size);}
};
struct Page {UInt64 address{0};vm_prot_t protection{0},maximum{0};bool writable{false};};
inline bool protection(const Context& context,vm_map_t map,UInt64 page,vm_prot_t& current,vm_prot_t& maximum) {
    natural_t depth=0;
    for(unsigned i=0;i<8;++i){
        mach_vm_address_t address=page;mach_vm_size_t size=0;
        vm_region_submap_short_info_data_64_t info{};
        mach_msg_type_number_t count=VM_REGION_SUBMAP_SHORT_INFO_COUNT_64;
        if(context.query(map,&address,&size,&depth,reinterpret_cast<vm_region_recurse_info_t>(&info),&count)!=KERN_SUCCESS
           ||count<VM_REGION_SUBMAP_SHORT_INFO_COUNT_64||address>page||page-address>=size||size-(page-address)<PageSize)return false;
        if(!info.is_submap){current=info.protection;maximum=info.max_protection;return true;}
        if(depth==~0U)return false;++depth;
    }
    return false;
}
inline bool payloadRX(const Context& context,vm_map_t map,UInt64 page) {
    vm_prot_t current=0,maximum=0;
    return protection(context,map,page,current,maximum)&&current==(VM_PROT_READ|VM_PROT_EXECUTE)&&maximum==current;
}
struct Ops {
    const Context& context;vm_map_t map;
    bool check(Page& p){return protection(context,map,p.address,p.protection,p.maximum)
        &&p.protection==(VM_PROT_READ|VM_PROT_EXECUTE)&&(p.maximum&p.protection)==p.protection;}
    bool makeWritable(Page& p){
        if(p.writable)return true;
        if(vm_protect(map,p.address,PageSize,FALSE,VM_PROT_READ|VM_PROT_WRITE|VM_PROT_COPY)!=KERN_SUCCESS)return false;
        p.writable=true;return true;
    }
    bool prepareRollback(Page* pages,UInt32 count,UInt64 address,UInt32 size){
        const auto last=(address+size-1)&~UInt64(PageSize-1);bool ok=true;
        for(UInt64 page=address&~UInt64(PageSize-1);page<=last;page+=PageSize){
            bool seen=false;
            for(UInt32 i=0;i<count;++i)if(pages[i].address==page){seen=true;if(!makeWritable(pages[i]))ok=false;}
            if(!seen)ok=false;
        }
        return ok;
    }
    bool restore(Page* pages,UInt32 count){
        bool ok=true;
        for(UInt32 i=0;i<count;++i){auto& p=pages[i];
            if(p.writable){auto status=vm_protect(map,p.address,PageSize,FALSE,p.protection);
                if(status!=KERN_SUCCESS)status=vm_protect(map,p.address,PageSize,FALSE,p.protection);
                if(status!=KERN_SUCCESS){ok=false;continue;}p.writable=false;}
            vm_prot_t current=0,maximum=0;
            if(!protection(context,map,p.address,current,maximum)||current!=p.protection||maximum!=p.maximum)ok=false;
        }
        return ok;
    }
    int write(const UInt8* bytes,UInt64 address,UInt32 size){return context.write(bytes,address,size);}
    int read(UInt64 address,UInt8* bytes,UInt32 size){return context.read(address,bytes,size);}
};
}
