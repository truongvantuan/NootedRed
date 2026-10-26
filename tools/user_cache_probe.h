// Read-only snapshots of this probe's own cache mappings; never writes to the cache.
#pragma once
#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>

static NSString* readHex(mach_vm_address_t address, size_t size) {
    NSMutableData* data = [NSMutableData dataWithLength:size];
    mach_vm_size_t count = 0;
    if (mach_vm_read_overwrite(mach_task_self(),address,size,
        reinterpret_cast<mach_vm_address_t>(data.mutableBytes),&count) != KERN_SUCCESS || count != size) return @"";
    NSMutableString* result = [NSMutableString stringWithCapacity:2*size];
    auto* bytes = static_cast<const uint8_t*>(data.bytes);
    for(size_t i=0;i<size;i++) [result appendFormat:@"%02x",bytes[i]];
    return result;
}
static NSDictionary* cacheSnapshot() {
    auto getRange = reinterpret_cast<const void*(*)(size_t*)>(dlsym(RTLD_DEFAULT,"_dyld_get_shared_cache_range"));
    size_t size = 0;
    const auto base = getRange ? reinterpret_cast<uint64_t>(getRange(&size)) : 0;
    if (!base) return @{@"available":@NO};
    auto version = NSProcessInfo.processInfo.operatingSystemVersion.majorVersion;
    uint64_t gate=version==14?0x30354D1BCULL:version==15?0x3087B3164ULL:version==26?0x310C77708ULL:0;
    uint64_t method=version==14?0x30355E210ULL:version==15?0x3087C3580ULL:version==26?0x310CE7240ULL:0;
    NSMutableDictionary* report = [@{@"available":@YES,@"cache_uuid_hex":readHex(base+88,16)} mutableCopy];
    if (gate) {
        report[@"metal_page_hex"] = readHex((base+gate)&~4095ULL,4096);
        report[@"gate_hex"] = readHex(base+gate,2);
        if(version!=26) report[@"allow_hex"] = readHex(base+(version==14?0x30354D1E1ULL:0x3087B3198ULL),3);
    }
    if (method) {
        report[@"submit_guard_method_address"] = @(base+method);
        NSString* entry = readHex(base+method,15); report[@"submit_guard_entry_hex"] = entry;
        if ([entry hasPrefix:@"ff2500000000"]) {
            uint64_t target = 0; mach_vm_size_t count = 0;
            if (mach_vm_read_overwrite(mach_task_self(),base+method+6,8,
                reinterpret_cast<mach_vm_address_t>(&target),&count)==KERN_SUCCESS && count==8) {
                report[@"submit_guard_target"] = @(target);
                report[@"submit_guard_payload_hex"] = readHex(target,307);
                mach_vm_address_t address = target; mach_vm_size_t regionSize = 0;
                vm_region_basic_info_data_64_t info{}; mach_msg_type_number_t fields=VM_REGION_BASIC_INFO_COUNT_64;
                mach_port_t object = MACH_PORT_NULL;
                if(mach_vm_region(mach_task_self(),&address,&regionSize,VM_REGION_BASIC_INFO_64,
                    reinterpret_cast<vm_region_info_t>(&info),&fields,&object)==KERN_SUCCESS
                    && address<=target && target-address<regionSize) report[@"submit_guard_payload_protection"]=@(info.protection);
                if(object!=MACH_PORT_NULL) mach_port_deallocate(mach_task_self(),object);
            }
        }
    }
    return report;
}
