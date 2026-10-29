// Read-only SRD/scratch planning. Workspace must live on the heap in kernel callers.
#pragma once
#include <UserSurface24H232Data.hpp>
namespace SurfaceExactPlan {
constexpr UInt32 SiteCount=4,MaxBytes=512;
enum class State { Rejected,Ready,Installed };
struct Workspace {
    UserVideoGuardTypes::Patch resolved[SiteCount]{},sites[SiteCount]{};
    UInt8 original[SiteCount][MaxBytes]{},patched[SiteCount][MaxBytes]{},observed[SiteCount][MaxBytes]{};
    UInt8 scan[UserSharedCache::Input::ScanSize]{};
    UInt32 count{0};State state{State::Rejected};
};
inline bool extraIdentity(UserSharedCache::Input& input,UInt64 base,const Workspace& w) {
    const auto address=base+w.resolved[0].offset;
    UInt64 constant=0,dump=0;
    if(!UserSharedCache::relativeTarget(address,135,w.original[0],constant)
       ||!UserSharedCache::relativeTarget(address,211,w.original[0],dump))return false;
    UInt8 value[sizeof(UserSurface24H232Data::NativeDump)];
    return input.read(constant,value,4)&&UserSharedCache::word(value)==0x40400000
        &&input.read(dump,value,sizeof(value))&&!memcmp(value,UserSurface24H232Data::NativeDump,sizeof(value));
}
// A stock or locally patched LegacyBlend gate is allowed before initial SRD
// publication. Other partially installed combinations are never treated as ready.
__attribute__((noinline)) inline bool build(UserSharedCache::Input& input,UInt64 base,UInt32 device,
                                          bool legacyBlend,Workspace& w) {
    w.count=0;w.state=State::Rejected;
    const auto* data=UserSurface24H232Data::findDevice(device);
    if(!data)return false;
    input.scanBuffer=w.scan;
    if(!UserCacheResolver::resolveExact(input,base,UserSurface24H232Data::CacheUUID,
        UserSurface24H232Data::ResolverImages,UserSurface24H232Data::ResolverFunctions,data,
        UserSurface24H232Data::ResolverLocations,w.resolved,&w.original[0][0],&w.patched[0][0],MaxBytes)
       ||!extraIdentity(input,base,w))return false;
    bool installed[SiteCount]{};
    for(UInt32 i=0;i<SiteCount;++i){
        const auto& p=w.resolved[i];
        if(!p.size||p.size>MaxBytes||!input.read(base+p.offset,w.observed[i],p.size))return false;
        if(!memcmp(w.observed[i],p.patched,p.size))installed[i]=true;
        else if(memcmp(w.observed[i],p.original,p.size))return false;
    }
    const UInt32 changed=UInt32(installed[0])+UInt32(installed[1])+UInt32(installed[3]);
    if(changed!=0&&changed!=3)return false;
    if(changed==3&&legacyBlend&&!installed[2])return false;
    for(UInt32 i=0;i<SiteCount;++i){
        // Do not enable, remove or roll back an independently owned blend gate
        // when its local option is disabled.
        if(i==2&&!legacyBlend)continue;
        const auto& p=w.resolved[i];
        w.sites[w.count++]={p.offset,w.observed[i],p.patched,p.size};
    }
    w.state=changed==3?State::Installed:State::Ready;
    return true;
}
inline bool samePlan(const Workspace& initial,const Workspace& fresh) {
    if(initial.state!=fresh.state||initial.count!=fresh.count||!initial.count)return false;
    for(UInt32 i=0;i<initial.count;++i){const auto& a=initial.sites[i];const auto& b=fresh.sites[i];
        if(a.offset!=b.offset||a.size!=b.size||memcmp(a.original,b.original,a.size)
           ||memcmp(a.patched,b.patched,a.size))return false;
    }
    return true;
}
}
