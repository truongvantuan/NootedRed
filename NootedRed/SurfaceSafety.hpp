#pragma once
#include <UserPrivateMemory.hpp>
namespace SurfaceSafety {
enum class Result { Rejected,Installed,Halted };
bool configure(UserPrivateMemory::CopyIn read,UserPrivateMemory::CopyOut write,UserPrivateMemory::Query query);
// Caller must enforce OS/device/option/FairPlay policy and hold the existing map lease.
Result install(vm_map_t map,UInt64 base,UInt32 device,bool legacyBlend,int pid);
}
