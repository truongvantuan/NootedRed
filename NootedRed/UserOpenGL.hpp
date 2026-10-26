// Conditional OpenGL repair owned by UserPatches' existing validation hooks.
#pragma once
#include <IOKit/IOTypes.h>

class UserOpenGL {
public:
    static constexpr UInt64 MaxFileSize = 32 * 1024 * 1024;
    static void init(UInt32 darwin, UInt32 deviceID, bool allowDynamic, bool forceDynamic);
    static void patchPage(const void* data, UInt64 offset);
    static void reportBudgetResult(bool applied, bool restored);
};
