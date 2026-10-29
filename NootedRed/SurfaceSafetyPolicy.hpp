// Experimental surface path is selected only for the generated current-build profile.
#pragma once
#include <string.h>
namespace SurfaceSafetyPolicy {
inline bool eligible(bool requested,const char* build,unsigned major,unsigned device){
    return requested&&build&&!strcmp(build,"24H232")&&major==24
        &&(device==0x15d8||device==0x15dd||device==0x15e7||device==0x1636||device==0x1638||device==0x164c);
}
}
