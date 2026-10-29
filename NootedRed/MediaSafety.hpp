#pragma once
#include <UserPrivateMemory.hpp>
namespace MediaSafety {
using CopyIn=UserPrivateMemory::CopyIn;
using CopyOut=UserPrivateMemory::CopyOut;
using Query=UserPrivateMemory::Query;
bool configure(CopyIn read,CopyOut write,Query query);
// Caller must hold the existing map lease, enforce policy/FairPlay and bridge readiness.
void install(vm_map_t map,UInt64 base,int pid);
}
