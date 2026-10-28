// Read-only complete-page media planner. Caller owns heap-backed workspace.
#pragma once
#include <UserVideoGuardTypes.hpp>
#include <string.h>
namespace MediaExactPlan {
constexpr UInt32 PageSize=4096,MaxPages=10,MaxSites=24,MaxBytes=64;
struct PageReference { UInt64 offset; const UInt8* bytes; };
enum class State { Rejected, Original, Patched, Mixed };
struct Workspace {
    UserVideoGuardTypes::Patch sites[MaxSites]{};
    UInt8 original[MaxSites][MaxBytes]{},patched[MaxSites][MaxBytes]{};
    UInt8 observed[PageSize]{},target[PageSize]{};
    UInt32 count{0}; State state{State::Rejected};
};
template<typename Input,typename Record>
__attribute__((noinline)) bool build(Input& input,UInt64 base,const PageReference* pages,UInt32 pageCount,
                                    const Record* va,size_t vaCount,const Record* gva,size_t gvaCount,Workspace& out) {
    out.count=0;out.state=State::Rejected;
    struct ClearRejected { Workspace& plan;bool accepted{false};~ClearRejected(){if(!accepted)plan.count=0;} } clear{out};
    if(!pages||!pageCount||pageCount>MaxPages||!va||!gva||vaCount>24||gvaCount>24)return false;
    UInt32 originals=0,patched=0,records=0;
    for(UInt32 p=0;p<pageCount;++p){
        const auto& page=pages[p];
        if(!page.bytes||(page.offset&(PageSize-1))||base>=0x800000000000ULL
           ||page.offset>=0x800000000000ULL-base-PageSize)return false;
        for(UInt32 j=0;j<p;++j)if(page.offset==pages[j].offset||page.bytes==pages[j].bytes)return false;
        memcpy(out.target,page.bytes,PageSize);
        for(unsigned table=0;table<2;++table){
            const auto* rows=table?gva:va;const auto count=table?gvaCount:vaCount;
            for(size_t r=0;r<count;++r){
                const auto& row=rows[r];if(row.page!=page.bytes)continue;++records;
                if(!row.find||!row.replace||!row.size||row.size>MaxBytes||!row.count||row.count>MaxSites||row.skip>MaxSites)return false;
                UInt32 matches=0,added=0;
                for(UInt32 off=0;off<=PageSize-row.size;++off){
                    if(memcmp(page.bytes+off,row.find,row.size)!=0)continue;
                    if(matches++<row.skip)continue;
                    if(added==row.count)continue;
                    if(out.count==MaxSites)return false;
                    const auto address=page.offset+off;
                    for(UInt32 j=0;j<out.count;++j){const auto& old=out.sites[j];
                        if(address<old.offset+old.size&&old.offset<address+row.size)return false;}
                    memcpy(out.original[out.count],row.find,row.size);
                    memcpy(out.patched[out.count],row.replace,row.size);
                    out.sites[out.count]={address,out.original[out.count],out.patched[out.count],static_cast<UInt32>(row.size)};
                    ++out.count;++added;memcpy(out.target+off,row.replace,row.size);
                }
                if(added!=row.count)return false;
            }
        }
        if(!input.read(base+page.offset,out.observed,PageSize))return false;
        if(memcmp(out.observed,page.bytes,PageSize)==0)++originals;
        else if(memcmp(out.observed,out.target,PageSize)==0)++patched;
        else return false;
    }
    if(records!=vaCount+gvaCount||!out.count)return false;
    out.state=originals==pageCount?State::Original:patched==pageCount?State::Patched:State::Mixed;
    clear.accepted=out.state!=State::Mixed;
    return clear.accepted;
}
}
