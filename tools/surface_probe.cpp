// Read-only verification of this process's own surface cache mappings; no GPU objects.
#include <SurfaceExactPlan.hpp>
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <dlfcn.h>
#include <cstdio>
#include <cstring>
#include <memory>
#include <unistd.h>
static int readSelf(UInt64 address,void* bytes,size_t size){
    mach_vm_size_t copied=0;
    const auto result=mach_vm_read_overwrite(mach_task_self(),address,size,reinterpret_cast<mach_vm_address_t>(bytes),&copied);
    return result==KERN_SUCCESS&&copied==size?0:1;
}
static bool isRX(UInt64 address,UInt32 size){
    const UInt64 last=(address+size-1)&~UInt64(4095);
    for(UInt64 page=address&~UInt64(4095);page<=last;page+=4096){
        natural_t depth=0;bool leaf=false;
        for(unsigned attempt=0;attempt<8;++attempt){
            mach_vm_address_t start=page;mach_vm_size_t length=0;
            vm_region_submap_short_info_data_64_t info{};
            mach_msg_type_number_t count=VM_REGION_SUBMAP_SHORT_INFO_COUNT_64;
            const auto status=mach_vm_region_recurse(mach_task_self(),&start,&length,&depth,
                reinterpret_cast<vm_region_recurse_info_t>(&info),&count);
            if(status!=KERN_SUCCESS||count<VM_REGION_SUBMAP_SHORT_INFO_COUNT_64||start>page||page-start>=length
               ||length-(page-start)<4096)return false;
            if(info.is_submap){++depth;continue;}
            if(info.protection!=(VM_PROT_READ|VM_PROT_EXECUTE))return false;
            leaf=true;break;
        }
        if(!leaf)return false;
    }
    return true;
}
int main(int argc,const char* argv[]){
    bool requireInstalled=false,blend=true;
    for(int i=1;i<argc;++i){
        if(!strcmp(argv[i],"--require-installed"))requireInstalled=true;
        else if(!strcmp(argv[i],"--no-blend"))blend=false;
        else {fprintf(stderr,"usage: surface_probe [--require-installed] [--no-blend]\n");return 64;}
    }
    auto getRange=reinterpret_cast<const void*(*)(size_t*)>(dlsym(RTLD_DEFAULT,"_dyld_get_shared_cache_range"));
    size_t cacheSize=0;const auto base=getRange?reinterpret_cast<UInt64>(getRange(&cacheSize)):0;
    auto plan=std::make_unique<SurfaceExactPlan::Workspace>();
    UserSharedCache::Input input{readSelf,{}};
    const bool accepted=base&&cacheSize&&SurfaceExactPlan::build(input,base,0x1636,blend,*plan);
    bool permissions=accepted;
    for(UInt32 i=0;accepted&&i<plan->count;++i)permissions=permissions&&isRX(base+plan->sites[i].offset,plan->sites[i].size);
    const bool installed=accepted&&permissions&&plan->state==SurfaceExactPlan::State::Installed;
    printf("{\n  \"pid\": %d,\n  \"device_profile\": \"0x1636\",\n  \"profile_accepted\": %s,\n  \"selected_sites\": %u,\n  \"current_RX\": %s,\n  \"fully_installed\": %s,\n  \"reads\": %u,\n  \"bytes_read\": %u,\n  \"GPU_work_submitted\": false,\n  \"scope\": \"Own-process complete functions, references and surface bytes; not GPU output or another process\"\n}\n",
           getpid(),accepted?"true":"false",plan->count,permissions?"true":"false",installed?"true":"false",input.reads,input.bytes);
    return accepted&&permissions&&(!requireInstalled||installed)?0:1;
}
