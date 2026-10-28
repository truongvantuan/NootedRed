// Exact 24H232 reference layout, derived from generated headers by tools/gen_media_layout.py.
#pragma once
#include <MediaExactPlan.hpp>
#include <VDAVADataSequoia24H232.hpp>
#include <VDAGVADataSequoia24H232.hpp>
namespace MediaReference24H232 {
inline constexpr MediaExactPlan::PageReference Pages[]={
    {0x308606000ULL,VDAVADataSequoia24H232::Page0},
    {0x308608000ULL,VDAVADataSequoia24H232::Page1},
    {0x30860F000ULL,VDAVADataSequoia24H232::Page2},
    {0x30864C000ULL,VDAVADataSequoia24H232::Page3},
    {0x30864D000ULL,VDAVADataSequoia24H232::Page4},
    {0x30864F000ULL,VDAVADataSequoia24H232::Page5},
    {0x308650000ULL,VDAVADataSequoia24H232::Page6},
    {0x308667000ULL,VDAVADataSequoia24H232::Page7},
    {0x30867D000ULL,VDAVADataSequoia24H232::Page8},
    {0x206696000ULL,VDAGVADataSequoia24H232::Page0},
};
}
