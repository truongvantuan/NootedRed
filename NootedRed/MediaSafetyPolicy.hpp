// Candidate ownership gate; hardware acceptance is required before default promotion.
#pragma once
#include <string.h>
namespace MediaSafetyPolicy {
inline bool eligible(bool requested,const char* build,unsigned major,unsigned device) {
    return requested && build && strcmp(build,"24H232")==0 && major==24
        && (device==0x15e7 || device==0x1636 || device==0x1638 || device==0x164c);
}
}
