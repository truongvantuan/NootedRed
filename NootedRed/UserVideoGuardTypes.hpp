// Guard-only patch descriptors. No fork VA adaptation payload or second patch owner.
#pragma once
#include <IOKit/IOTypes.h>
#include <stddef.h>
namespace UserVideoGuardTypes {
struct Patch { UInt64 offset; const UInt8* original; const UInt8* patched; UInt32 size; };
}
