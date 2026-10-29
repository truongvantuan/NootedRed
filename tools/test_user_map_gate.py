"""执行真实共享缓存钩子，验证独立进程不被另一进程的扫描阻塞。"""
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'build/user-map-gate-test'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sanitize', choices=['address', 'thread'], default='address')
    args = parser.parse_args()
    from test_patch_dispatch import method
    text=(ROOT/'NootedRed/UserPatches.cpp').read_text()
    wrapper=method(text,'__attribute__((noinline)) int UserPatches::wrapSharedRegionCheck(')
    use_helper=True
    source = r'''
#include <cassert>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstdint>
#include <memory>
#include <map>
#include <mutex>
#include <thread>
#include <vector>
using UInt32=uint32_t;using task_t=void*;using proc_t=void*;using IOLock=std::mutex;
constexpr int THREAD_UNINT=0;
static std::map<void*,std::condition_variable_any> gateEvents;
static void IOLockLock(IOLock* p){p->lock();}
static void IOLockUnlock(IOLock* p){p->unlock();}
static int IOLockSleep(IOLock* p,void* event,int){auto& changed=gateEvents[event];std::unique_lock held(*p,std::adopt_lock);changed.wait(held);held.release();return 0;}
static void IOLockWakeup(IOLock*,void* event,bool){auto found=gateEvents.find(event);if(found!=gateEvents.end())found->second.notify_all();}
HELPER
static IOLock lock;static IOLock* cachePatchLock=&lock;
REGISTRY
static thread_local task_t task=nullptr;
static thread_local int threadIdentity;
static void* current_thread(){return &threadIdentity;}
static task_t current_task(){return task;}
static void* mapForTask(task_t task){return task==reinterpret_cast<void*>(3)?reinterpret_cast<void*>(1):task;}
static auto getTaskMap=mapForTask;
static auto getTaskMapFunc=mapForTask;
struct SharedRegionCheckArgs {uint64_t startAddress;};
static std::mutex state;static std::condition_variable changed;
static bool aEntered=false,bEntered=false,releaseA=false;
static std::atomic<unsigned> nativeCalls{0},patchCalls{0},rejections{0};static int nativeStatus=0;static unsigned aInside=0,aPeak=0;
static int original(proc_t,void*,int* out){nativeCalls++;*out=123;return nativeStatus;}
static int patchSharedRegion(proc_t,SharedRegionCheckArgs*,int result){
 ++patchCalls;
 std::unique_lock held(state);
 if(getTaskMap(task)==reinterpret_cast<void*>(1)){
  aPeak=std::max(aPeak,++aInside);aEntered=true;changed.notify_all();
  changed.wait(held,[]{return releaseA;});aInside--;
 }else{bEntered=true;changed.notify_all();}
 return result;
}
struct UserPatches {
 bool submitGuardEnabled=true,legacyBlendEnabled=true,mediaSafetyEnabled=false,surfaceSafetyEnabled=false;
 uintptr_t orgSharedRegionCheck=0;
 static UserPatches& singleton(){static UserPatches p;return p;}
 static int wrapSharedRegionCheck(proc_t,void*,int*);
 void applySubmitGuard(proc_t p,void* a){patchSharedRegion(p,static_cast<SharedRegionCheckArgs*>(a),0);}
};
struct NRed {static NRed& singleton(){static NRed n;return n;}void setProp32(const char*,unsigned){++rejections;}};
#define FunctionCast(name,address) reinterpret_cast<decltype(&name)>(address)
WRAPPER
static void run(unsigned key){task=reinterpret_cast<void*>(uintptr_t(key));SharedRegionCheckArgs args{0x1000};int out=0;
 assert(UserPatches::wrapSharedRegionCheck(task,&args,&out)==0&&out==123);}
int main(){
 UserPatches::singleton().orgSharedRegionCheck=reinterpret_cast<uintptr_t>(original);
 std::thread first([]{run(1);});
 {std::unique_lock held(state);assert(changed.wait_for(held,std::chrono::seconds(2),[]{return aEntered;}));}
 std::thread duplicate([]{run(3);}),independent([]{run(2);});
 bool independentProgress;
 {std::unique_lock held(state);independentProgress=changed.wait_for(held,std::chrono::milliseconds(500),[]{return bEntered;});releaseA=true;changed.notify_all();}
 first.join();duplicate.join();independent.join();
 assert(nativeCalls==3&&aPeak==1);
 assert(independentProgress);
 STRESS
 puts("PASS local hook: independent-map progress, shared-map exclusion, saturation/wakeup, 1600 leases, reentry/null rejection and native-result preservation");
}
'''
    stress = r'''
 UserPatchMapGate::Registry<4> registry;
 using Lease=UserPatchMapGate::Lease<4>;
 std::vector<std::unique_ptr<Lease>> leases;
 for(unsigned i=0;i<4;i++)leases.emplace_back(new Lease(registry,&lock,reinterpret_cast<void*>(uintptr_t(i+10)),reinterpret_cast<void*>(uintptr_t(i+100))));
 std::atomic<bool> waiting{false},entered{false};
 std::thread fifth([&]{waiting=true;Lease lease(registry,&lock,reinterpret_cast<void*>(20),current_thread());assert(lease);entered=true;});
 while(!waiting)std::this_thread::yield();
 {std::lock_guard held(lock);assert(!entered);}
 leases[0].reset();fifth.join();assert(entered);leases.clear();
 std::atomic<unsigned> active[4]{};std::vector<std::thread> threads;
 for(unsigned n=0;n<16;n++)threads.emplace_back([&,n]{for(unsigned i=0;i<100;i++){
  unsigned key=n%4;Lease lease(registry,&lock,reinterpret_cast<void*>(uintptr_t(key+1)),current_thread());assert(lease);
  assert(active[key].fetch_add(1)==0);std::this_thread::yield();assert(active[key].fetch_sub(1)==1);
 }});
 for(auto& t:threads)t.join();
 for(auto key:registry.keys)assert(key==nullptr);
 assert(registry.active==0&&registry.peak==4);
 // Reentry by the active thread must reject immediately, even for a different map.
 {
  Lease outer(registry,&lock,(void*)1,current_thread());assert(outer);
  Lease nested(registry,&lock,(void*)1,current_thread());assert(!nested);
  Lease otherMap(registry,&lock,(void*)2,current_thread());assert(!otherMap);
 }
 assert(!registry.active);
 {Lease missing(registry,nullptr,(void*)1,current_thread());assert(!missing);}
 {Lease missing(registry,&lock,nullptr,current_thread());assert(!missing);}
 {Lease missing(registry,&lock,(void*)1,nullptr);assert(!missing);}
 // The actual wrapper preserves native failure/output and disabled/null paths.
 task=(void*)9;SharedRegionCheckArgs args{0};int output=0;auto before=patchCalls.load();
 nativeStatus=5;assert(UserPatches::wrapSharedRegionCheck(task,&args,&output)==5&&output==123);
 assert(patchCalls==before&&!cachePatchMaps.active);nativeStatus=0;
 assert(UserPatches::wrapSharedRegionCheck(task,nullptr,&output)==0&&patchCalls==before);
 auto& p=UserPatches::singleton();p.submitGuardEnabled=p.legacyBlendEnabled=false;
 assert(UserPatches::wrapSharedRegionCheck(task,&args,&output)==0&&patchCalls==before);
 p.submitGuardEnabled=p.legacyBlendEnabled=true;
 {UserPatchMapGate::Lease<64> outer(cachePatchMaps,&lock,getTaskMap(task),current_thread());assert(outer);
  assert(UserPatches::wrapSharedRegionCheck(task,&args,&output)==0&&patchCalls==before);}
 assert(rejections==1&&!cachePatchMaps.active);
 auto* savedLock=cachePatchLock;cachePatchLock=nullptr;
 assert(UserPatches::wrapSharedRegionCheck(task,&args,&output)==0&&patchCalls==before);cachePatchLock=savedLock;
 assert(rejections==2&&!cachePatchMaps.active);

'''
    source = source.replace('WRAPPER', wrapper)
    source = source.replace('HELPER', '#include <UserPatchMapGate.hpp>' if use_helper else '')
    source = source.replace('REGISTRY', 'static UserPatchMapGate::Registry<64> cachePatchMaps;' if use_helper else '')
    source = source.replace('STRESS', stress if use_helper else '')
    WORK.mkdir(parents=True, exist_ok=True)
    path, exe = WORK / ('test-' + args.sanitize + '.cpp'), WORK / ('test-' + args.sanitize)
    path.write_text(source)
    sanitize = '-fsanitize=address,undefined' if args.sanitize == 'address' else '-fsanitize=thread'
    subprocess.run(['xcrun', 'clang++', '-std=c++23', '-O2', sanitize,
                    '-fno-omit-frame-pointer', '-fno-sanitize-recover=all', '-I' + str(ROOT / 'NootedRed'), str(path), '-o', str(exe)],
                   check=True, timeout=60)
    subprocess.run([str(exe)], check=True, timeout=10)


if __name__ == '__main__':
    main()
