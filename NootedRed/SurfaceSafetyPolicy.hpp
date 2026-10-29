// Experimental surface path is selected only for the generated current-build profile.
#pragma once
#include <string.h>
namespace SurfaceSafetyPolicy {
// osversion is populated after early kext initialization. Preparing callbacks
// authorizes no writes; the process-time build gate and exact cache plan do that.
inline bool canPrepare(bool requested,unsigned major,unsigned device){
    return requested&&major==24
        &&(device==0x15d8||device==0x15dd||device==0x15e7||device==0x1636||device==0x1638||device==0x164c);
}
inline bool eligible(bool prepared,const char* build,unsigned major,unsigned device){
    return canPrepare(prepared,major,device)&&build&&!strcmp(build,"24H232");
}
}
