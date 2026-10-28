#pragma once
#include <IOKit/IOTypes.h>
#include <mach/vm_map.h>
#include <mach/vm_region.h>
namespace MediaSafety {
using CopyIn=int (*)(const void*,void*,size_t);
using CopyOut=int (*)(const void*,void*,size_t);
using Query=kern_return_t (*)(vm_map_t,mach_vm_address_t*,mach_vm_size_t*,natural_t*,vm_region_recurse_info_t,mach_msg_type_number_t*);
bool configure(CopyIn read,CopyOut write,Query query);
// Caller must hold the existing map lease, enforce policy/FairPlay and bridge readiness.
void install(vm_map_t map,UInt64 base,int pid);
}
