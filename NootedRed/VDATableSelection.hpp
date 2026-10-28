// Build-qualified tables supersede the existing fallback set only on an exact match.
#pragma once
#include <string.h>
namespace VDATableSelection {
template<typename Table> inline bool hasSpecific(const Table* tables, size_t count, const char* build) {
    if (!build || !*build) { return false; }
    for (size_t i=0;i<count;++i) {
        if (tables[i].build && strcmp(tables[i].build,build)==0) { return true; }
    }
    return false;
}
template<typename Table> inline bool selected(const Table& table, bool specific, const char* build) {
    return specific ? table.build && build && strcmp(table.build,build)==0 : table.build==nullptr;
}
}
