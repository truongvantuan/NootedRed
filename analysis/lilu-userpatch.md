# Lilu user-space patching: what works, what does not, and what NootedRed does instead

Status: implemented in `NootedRed/UserPatches.hpp` and `NootedRed/UserPatches.cpp`, not yet integrated
into `NRed.cpp`. Target: macOS 15.8.1 (Sequoia, Darwin 24.6.0, x86_64), AMD Renoir `0x1638`, NootedRed
loaded. Patch bytes and page images still have to be filled in from `analysis/gl-hwinfo.md`.

## 1. Verdict (TL;DR)

1. Lilu's `onProcLoad` / `UserPatcher` **cannot work on macOS 11 and newer**, and therefore cannot work
   on this system. It is not a limitation of how the requests are registered: upstream Lilu explicitly
   disables the whole user patcher for `getKernelVersion() >= BigSur` (AppleForge submodule, Lilu
   1.7.2, `Sources/kern_start.cpp:247`). `lilu.onProcLoad()` still returns `Error::NoError` and stores
   the requests, but nothing is ever hooked or patched. `-liluslow` / `-lilufast` do not change this.
2. Even if that check were removed, Lilu would still miss this driver. Lilu routes `_cs_validate_range`
   and only falls back to `_cs_validate_page` when the range symbol cannot be routed
   (`Sources/kern_user.cpp:1057`). On macOS 11+ a vnode-backed bundle such as
   `AMDRadeonX5000GLDriver` is validated through **`_cs_validate_page`** on the page fault path, while
   `_cs_validate_range` is only used by the dyld shared cache pager and the Apple-protected pager.
   The driver is not part of the shared cache on 15.8.1 (only `ATIRadeonX5000SCLib.dylib` is listed in
   `/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld/dyld_shared_cache_x86_64h.map`).
3. The page-patching *mechanism* Lilu used up to Catalina still works on Big Sur through Tahoe, it just
   has to be implemented by NootedRed itself against the current code signing functions. That is what
   `UserPatches` does: it routes `_cs_validate_page` (and `_cs_validate_range` when available), waits
   for a page to validate successfully, and then rewrites the already-validated physical page through
   the kernel mapping. It is fully page-content based: a complete 4 KiB page image has to be byte
   identical before anything is written, exactly like Lilu's `performPagePatch`.
4. Because the whole page is the match key, the table is version/build specific and fails safe: if the
   user updates macOS and the driver page changes, nothing matches and nothing is patched.
5. On macOS 10.15 and older the module still registers a regular Lilu user patch (that is the only
   backend Lilu supports, and the `find`/`replace`/`skip`/`count` table is shared between backends).

## 2. Lilu API sequence (what a plugin normally does)

Everything below is from the AppleForge Lilu checkout at `../AppleForge/Lilu/Lilu`.

Registration (from the plugin start routine, before Lilu processes its request lists):

```cpp
// plugin init
lilu.onPatcherLoad(callback, user);                          // Kernels: fires once the patcher is ready
// inside callback (or at init, both work as long as it happens before performCommonInit()):
lilu.onProcLoad(procs, procNum, callback, user, mods, modNum); // kern_api.cpp:174
```

Lilu then does, in order (`Sources/kern_start.cpp:performCommonInit`):

1. `lilu.processPatcherLoadCallbacks(kernelPatcher)` - the callback above.
2. `userPatcher.init(kernelPatcher, preferSlowMode)` - registers a `KAUTH_SCOPE_FILEOP` listener
   (`kern_user.cpp:105`), stores `patchDyldSharedCache = !preferSlowMode`.
3. `lilu.processUserLoadCallbacks(userPatcher)` (`kern_api.cpp:340`) - drops disabled `ProcInfo`s and
   calls `UserPatcher::registerPatches` (`kern_user.cpp:127`), which:
   - `loadFilesForPatching()` (`kern_user.cpp:817`): for every `BinaryModInfo`, `FileIO::readFileToBuffer`
     the binary from disk, then for every enabled `BinaryModPatch` runs `MachInfo::findSectionBounds`
     for the segment/section named by `FileSegment` (`__TEXT`/`__text` etc.), scans the whole section for
     `find` (`skip`/`count` decide which occurrences are used), and for every hit copies the containing
     4 KiB file page into `lookupStorage` and records the patch offset inside that page;
   - `loadDyldSharedCacheMapping()` (`kern_user.cpp:752`): if the shared cache path is among the
     `BinaryModInfo`s, parses the `.map` for its `__TEXT`/`__DATA` VM ranges (used only for
     `patchSharedCache`, i.e. shared-cache images);
   - `loadLookups()` (`kern_user.cpp:975`): differentiates the stored pages by picking four 8-byte
     offsets with pairwise distinct values (this is the fast pre-filter);
   - `hookMemoryAccess()` (`kern_user.cpp:1057`): routes `_cs_validate_range` (10.12+), or
     `_cs_validate_page` only if the range route failed, then resolves `_current_map`, `_get_map_min`,
     `_get_task_map`, `_vm_map_check_protection`, `_vm_map_read_user`, `_vm_map_write_user`, etc.
4. When a matching process execs, the kauth listener calls `UserPatcher::onPath` (a `ProcInfo` match).
   That either queues the patch or calls `patchBinary`, which patches the dyld shared cache for that
   process (`patchSharedCache`) or falls back to injecting a `__RESTRICT` segment (`injectRestrict`).
5. Independently of any process match, every validated page goes through `performPagePatch`
   (`kern_user.cpp:166`, called from `codeSignValidatePageWrapper`/`codeSignValidateRangeWrapper`):
   compare the four learned 8-byte words, then `memcmp` the whole `PAGE_SIZE` against the stored page,
   then - for each recorded offset and unless the patch has `LocalOnly` set - write `replace` over
   `find` with kernel write protection temporarily disabled.

`procNum = 0` is safe:
- `LiluAPI::onProcLoad` iterates `for (i = 0; i < num; i++)`, so no `infos` dereference;
- `UserPatcher::registerPatches` only derives `currentMinProcLength` inside `if (procNum)`;
- `UserPatcher::onPath` iterates `procInfoSize` entries, so with zero entries no callback can fire;
- `LiluAPI::processUserLoadCallbacks` proceeds as long as `storedBinaryMods` is non-empty, so page
  patching still gets installed.

This is exactly what the module registers on 10.15: `nullptr, 0, nullptr, nullptr, mods, modNum`. It is
deliberate - a `ProcInfo` list is only needed to trigger the per-process shared-cache patching and the
`__RESTRICT` injection, neither of which should happen here. Do not "fix" it by registering a wildcard
`ProcInfo`: `patchBinary` would add a `__RESTRICT` load command to every matched process.

`UserPatcher::LocalOnly` is only consulted in `performPagePatch` (skip global page patches). It is the
opposite of what a bundle-wide fix wants, so the module leaves `flags = 0`.

`BinaryModPatch::section` is not a section index in current Lilu - it is an enable id.
`ProcInfo::SectionDisabled` is `0`, and both `loadFilesForPatching` and `processUserLoadCallbacks`
skip patches whose `section` is zero. Use any non-zero value (the module uses `1`); WhateverGreen's CDF
patches do the same.

Lifetime: Lilu stores bare pointers to `ProcInfo`s, `BinaryModInfo`s, `BinaryModPatch`es and to the
`find`/`replace` buffers, so all of those must live as long as the kext does (file-scope statics).

## 3. Why Lilu cannot do it on macOS 15.8.1

### 3.1 The user patcher is disabled on Big Sur and newer

`Sources/kern_start.cpp:240`:

```cpp
isUserDisabled = checkKernelArgument(bootargUserOff) ||
    getKernelVersion() <= KernelVersion::SnowLeopard || getKernelVersion() >= KernelVersion::BigSur;
```

`bootargUserOff` is `-liluuseroff`. Consequences on 15.8.1:

- `UserPatcher::init` returns `true` immediately without registering the kauth listener
  (`kern_user.cpp:105`), and `UserPatcher::registerPatches` returns `true` immediately without reading
  any file or hooking anything (`kern_user.cpp:127`). `lilu.onProcLoad()` still returns `NoError`, so a
  plugin sees no failure at all, and the "disabling user patcher on request!" log is a `DBGLOG` only.
- `-liluslow` (`bootargSlow`) only forces `preferSlowMode`, which is irrelevant once the patcher is
  disabled; `-lilufast` (`bootargFast`) is the inverse. Neither can re-enable it.
- `-liluoff` disables Lilu itself, so NootedRed would not run at all. `-liluuseroff` is the argument
  that disables this subsystem specifically.
- The check is against the kernel version, not the presence of any symbol, so there is no boot argument
  that re-enables it on Big Sur+.

This is why the module only registers a Lilu user patch on `currentKernelVersion() < MACOS_11`.

### 3.2 Even if it were enabled, it would hook the wrong function

Verified against the actual 15.8.1 kernel binary (`/System/Library/Kernels/kernel`, x86_64) and the XNU
sources:

| symbol | 15.8.1 address | macOS <= 10.15 | macOS >= 11 |
| --- | --- | --- | --- |
| `_cs_validate_range` | `0xffffff800086cc10` | used for all vnode page-in faults | used only by `shared_region_pager_data_request` and `apple_protect_pager_data_request` |
| `_cs_validate_page` | `0xffffff800086d470` | does not exist | used for vnode page-in faults (`vm_fault_enter` -> `vm_page_map_and_validate_cs` -> `vm_page_validate_cs_mapped_slow`) |

Cross-checks:

- `nm -n /System/Library/Kernels/kernel | grep cs_validate` lists both symbols.
- In the disassembly, the only direct caller of `cs_validate_range` is
  `_vm_page_validate_cs_mapped_chunk` (`0xffffff80003a0eb7`); the callers of `cs_validate_page` are the
  static per-page validator used by `vm_fault_enter` (`0xffffff800039a7fc`),
  `_revalidate_text_page` (`0xffffff80003a1276`) and `_vm_page_copy` (`0xffffff80003ec642`).
- XNU `osfmk/vm/vm_fault.c` (`vm_page_map_and_validate_cs` in xnu-7195.141.2 and xnu-12377.121.6)
  maps the page with `VM_PROT_READ` and calls `vm_page_validate_cs_mapped_slow`, which calls
  `cs_validate_page`. `vm_page_validate_cs_mapped_chunk` (the range user) is only reachable from the
  shared-region and Apple-protect pagers.
- Current prototypes (BSD `kern/ubc_subr.c`, xnu-7195.141.2 and xnu-12377.121.6):

```c
void cs_validate_page(struct vnode *vp, memory_object_t pager, memory_object_offset_t page_offset,
                      const void *data, int *validated_p, int *tainted_p, int *nx_p);
boolean_t cs_validate_range(struct vnode *vp, memory_object_t pager, memory_object_offset_t page_offset,
                            const void *data, vm_size_t dsize, unsigned *tainted);
```

`cs_validate_page` is a **7-argument, `void`-returning** function with three out-parameters. Lilu's
`codeSignValidatePageWrapper` is the old 5-argument form (`kern_user.hpp` /
`Sources/kern_user.cpp:261`) and would corrupt the stack if it were ever routed on a modern kernel.
Lilu never does so because the range route always succeeds there. This is a second, independent reason
not to try to build on Lilu's user patcher.

`cs_validate_page` was introduced in Big Sur (it is absent from xnu-6153.141.1); Catalina and older only
had `cs_validate_range`, which is why a page-content patch worked there with Lilu.

## 4. The implemented backend

`NootedRed/UserPatches.cpp`:

1. `UserPatches::init()` is called from `NRed::init()`. It parses the boot arguments and registers a
   `lilu.onPatcherLoad` callback (non-fatal if that fails).
2. `processPatcher()` picks a backend by kernel version and does nothing if the table is empty.
3. `>= macOS 11`: `installNativePagePatcher()` routes `_cs_validate_page` (`KernelID`,
   `routeMultipleLong`, long jump) and best-effort `_cs_validate_range`. NootedRed already routes
   kernel-resident symbols through `KernelPatcher::KernelID` in production
   (`PenguinWizardry/RuntimeMC.cpp:43`, `DriverInjector.cpp:63`), so this mechanism is proven on this
   machine.
4. `wrapCsValidatePage` calls the original first, and only if `*validated_p != 0` (the page passed its
   code signature hash check) calls `patchNativePage(data)`. Patching before the original would make
   the hash check fail and get the process killed.
5. `patchNativePage` compares the whole 4 KiB buffer against each stored page image, verifies `find`
   at the recorded offsets, disables kernel write protection (`MachInfo::setKernelWriting(true,
   KernelPatcher::kernelWriteLock)`), writes `replace`, and restores it. No allocation, no file I/O and
   no blocking calls happen inside the hooks.
6. `< macOS 11`: `installUserPatcher()` fills a static `BinaryModPatch`/`BinaryModInfo` pair and calls
   `lilu.onProcLoad(nullptr, 0, nullptr, nullptr, &liluModInfo, 1)` as described in section 2.

Format of `UserPatches::PagePatch` (same idea as `UserPatcher::BinaryModPatch`):

```cpp
struct PagePatch {
    UserPatcher::FileSegment segment; // Lilu backend only (e.g. SegmentTextText for __TEXT,__text)
    const UInt8* page;                // native backend: exact 4 KiB file page containing find
    const UInt8* find;
    const UInt8* replace;
    size_t size;                      // bytes in find/replace
    size_t skip;                      // occurrences to skip
    size_t count;                     // occurrences to patch (must be non-zero)
};
```

The native backend counts `skip`/`count` occurrences inside the stored page only; the Lilu backend
counts them over the whole section, like Lilu itself. Put every occurrence into the table as its own
entry if a patch is repeated in several pages.

## 5. Caveats, in the order they bite

- **Everything is version/build specific.** The page image is the match key. After an OS update the
  image changes, nothing matches, and no patch is applied (safe failure, but the bug comes back). Log
  it with `-NRedDebug` (`DBGLOG("UserPatch", ...)` reports successful page matches).
- **The Lilu backend needs the file system at kext-load time.** Lilu reads the target binary itself in
  `registerPatches` (`FileIO::readFileToBuffer` in `loadFilesForPatching`), which runs from Lilu's early
  init. If the root volume is not readable at that point the read fails with a Lilu `SYSLOG("file",
  ...)` and the page patches silently do not exist. The macOS 11+ backend avoids runtime file I/O
  completely by embedding the page images in the kext, so only the table build at compile time depends
  on the driver binary.
- **Code signing.** The patch rewrites the page *after* the kernel verified its hash, using the kernel
  mapping of the physical page. The hash/signature embedded in the file is not changed and no
  validation result is forged. Resident pages are normally validated exactly once (the fault path
  checks `page->vmp_cs_validated`), so nothing re-hashes the patched page. This is the same class of
  modification Lilu's user patcher has always performed.
- **The kernel mapping is read-only.** `vm_page_map_and_validate_cs` maps the page with
  `VM_PROT_READ`, so writing it requires `CR0.WP` to be cleared, which is what
  `MachInfo::setKernelWriting` does (same as Lilu's `performPagePatch`). Do not remove that.
- **Timing / already-running processes.** Patching happens on the first page validation of each
  physical page. Pages that are already resident and validated before the hook is installed are never
  patched, and the same physical page is shared by every process that maps it, so all future mappers
  get the patched page for free. In a normal boot NootedRed's patcher callback runs long before
  WindowServer or any other process loads the GL driver, so this is fine; it would not be fine if the
  kext were loaded after the driver was already in use.
- **Page size.** The engine is hardcoded to `0x1000` because this is x86_64 and the driver is signed
  with `Page size=4096` (`codesign -dv`), i.e. `blob->csb_hash_pageshift == 12 == PAGE_SHIFT`. Do not
  reuse it on 16 KiB-page systems without redoing the code signing page arithmetic. The range hook
  iterates the supplied buffer in `PAGE_SIZE` chunks for the same reason.
- **Shared cache vs bundle.** The GL driver bundle is a normal file-backed Mach-O and is not a member
  of the dyld shared cache on 15.8.1. If a future OS moves it into the cache, the range hook covers it
  (the table must then be keyed on the cache page content), but 4 KiB page matching against a cached
  page is only guaranteed for the same cache build.
- **Sealed System Volume.** The file on disk cannot be modified (SSV + SIP); in-memory patching is the
  only option, and it disappears on reboot by design.
- **Swap/compression.** If a patched page is ever evicted to the compressor and faulted back in, in
  theory the code signing code could hash the patched content and taint it. In practice pages are
  validated when the page is first brought in from the vnode, not on every fault; this is the same
  exposure Lilu's user patcher had. Watch for `gpuRestart`/SIGABRT after memory pressure while testing.
- **PXE/performance.** `_cs_validate_page` runs for every executable page validation during boot, so
  the hook adds one 16-byte comparison per page, and a full 4 KiB comparison only for pages that pass
  the cheap check. That is negligible.
- **Failure behaviour.** Registration, symbol resolution and memory-write failures are `SYSLOG`ed and
  the module stays out of the way; nothing panics. If another plugin already routed
  `_cs_validate_page`, routing fails and the platform is left untouched.
- **KTRR/CTRR.** Routing kernel text relies on `KernelPatcher`'s standard `KernelID` code patching,
  which NootedRed already uses on this machine for `OSMetaClass::postModLoad` and
  `IOCatalogue::addDrivers`. It works here; it is not a new hack.
- **`-liluuseroff`** only affects the Lilu backend (macOS <= 10.15). The native backend is independent
  of Lilu's user patcher flags; `-NRedGLFix` / `-NRedGLFixOff` control it.
- **Don't put `ProcInfo` entries into the Lilu registration** (see section 2) - it would inject
  `__RESTRICT` into matched processes.

## 6. Boot arguments and logging

| argument | effect |
| --- | --- |
| `-NRedGLFix` | enables the feature (currently required, `kGLFixDefaultEnabled = false`) |
| `-NRedGLFixOff` | forces it off; wins over `-NRedGLFix` and over a future default-on |

Log tag is `UserPatch`. `SYSLOG` is used for enable/disable, missing/broken tables, routing failures
and write protection failures; `DBGLOG` (needs `-NRedDebug`) for successful registration and page
matches.

## 7. Filling the patch table

`analysis/gl-hwinfo.md` provides the exact patch sites. For each site:

- `find` / `replace` / `size`: the byte sequence to rewrite and its replacement (same length).
- `skip` / `count`: which occurrence to patch; `count` must be non-zero.
- `segment`: `UserPatcher::FileSegment::SegmentTextText` for `__TEXT,__text` (Lilu backend).
- `page`: the complete 4 KiB file page that contains `find` (native backend, macOS 11+).

Extracting a page image (page index is the file offset divided by 4096):

```sh
GL=/System/Library/Extensions/AMDRadeonX5000GLDriver.bundle/Contents/MacOS/AMDRadeonX5000GLDriver
dd if="$GL" of=page.bin bs=4096 skip=$((0xdf000 / 0x1000)) count=1 && xxd -i page.bin
```

A sanitised example entry (the bytes are placeholders, do not use them):

```cpp
static const UInt8 kGLDriverHwInfoPage[] = { /* 4096 bytes, xxd -i output */ };
static const UInt8 kGLDriverHwInfoFind[] = {0x48, 0x8B, 0x05, /* ... */};
static const UInt8 kGLDriverHwInfoReplace[] = {0x48, 0x8B, 0x0D /* ... */};
static const UserPatches::PagePatch kGLDriverPatches[] = {
    {UserPatcher::FileSegment::SegmentTextText, kGLDriverHwInfoPage, kGLDriverHwInfoFind, kGLDriverHwInfoReplace,
     sizeof(kGLDriverHwInfoFind), 0, 1},
};
```

The table can either replace the `kGLDriverPatches` stub inside `UserPatches.cpp`, or be passed in from
`NRed.cpp` with `registerGLDriverFix`. It has to be file scope (static storage duration).

## 8. Integration snippet for `NRed.cpp`

```cpp
#include <UserPatches.hpp>                                          // add with the other module includes
// ...
void NRed::init()
{
    // ... existing module initialisations ...
    UserPatches::singleton().init();                                // parses -NRedGLFix and queues the callback
    // Only if the table lives in NRed.cpp instead of UserPatches.cpp:
    // UserPatches::singleton().registerGLDriverFix(kGLDriverPatches, arrsize(kGLDriverPatches));
}
```

Two lines of actual code. `init()` and `registerGLDriverFix()` may be called in either order as long as
both happen from `NRed::init()` (i.e. before Lilu starts processing its request lists in
`performCommonInit`). Nothing else in `NRed.cpp`, `Plugin.cpp` or `xmake.lua` needs to change:
`add_files("NootedRed/**.cpp")` picks the new file up automatically.

## 9. Verification performed

- Compiles warning-free as part of the kext: `xmake f -m release -y && xmake -y` in a scratch copy of
  the tree with `AppleForgePath` pointing at the sibling checkout (`UserPatches.cpp` compiles and the
  kext links; the only warning produced by the new file was a shadowed parameter, since fixed).
- `_cs_validate_page` / `_cs_validate_range` presence and prototypes checked against the 15.8.1 kernel
  binary (symbols + disassembly + call sites) and against Apple's XNU sources for Big Sur
  (xnu-7195.141.2), Monterey (xnu-8019.41.5), Ventura (xnu-8792.41.9), Sonoma (xnu-10063.141.1),
  Sequoia (xnu-11417.140.69, the 15.8.1 kernel) and Tahoe (xnu-12377.121.6). The signatures and the
  fault-path call site are identical in all of them.
- The Lilu behaviour above was read out of the exact Lilu sources this project builds against
  (`../AppleForge/Lilu/Lilu`, v1.7.2, commit `0515f40`), including `kern_start.cpp`, `kern_user.cpp`
  and `kern_api.cpp`.
- The driver itself was inspected on the target machine: thin x86_64h Mach-O, `__TEXT` `fileoff 0`,
  `__text` at VM/file offset `0xfb0` size `0xebea6`, embedded signature with 4 KiB pages, not a
  shared-cache member.
- Not verified on hardware: no reboot or GL workload was run, so the first real test is booting with
  `-NRedGLFix` and a populated table.

## 10. Things to test once the table is populated

1. Boot with and without `-NRedGLFix`; check `log show --predicate 'eventMessage CONTAINS "UserPatch"'`
   for the expected `SYSLOG`/`DBGLOG` lines.
2. Start Chromium (or Sublime Text) with GPU rasterisation and dual-source blending, watch for
   `gpuRestart` / `Graphics hardware encountered an error` in the logs.
3. Check that other OpenGL applications (WindowServer, Safari WebGL) still work, since the hook is
   global to all page validation.
4. Sleep/wake and a `vm` pressure run to make sure patched pages survive eviction/compression.
5. Only then consider flipping `kGLFixDefaultEnabled` to `true`.

## 11. References

- Lilu sources: `../AppleForge/Lilu/Lilu/Sources/kern_start.cpp` (`isUserDisabled`),
  `Sources/kern_user.cpp` (user patcher), `Sources/kern_api.cpp` (`onProcLoad`/`processUserLoadCallbacks`),
  `Headers/kern_user.hpp` (ABI structs), `Headers/kern_api.hpp`.
- XNU: <https://github.com/apple-oss-distributions/xnu/blob/xnu-11417.140.69/bsd/kern/ubc_subr.c>
  (`cs_validate_page`, `cs_validate_range`),
  <https://github.com/apple-oss-distributions/xnu/blob/xnu-11417.140.69/osfmk/vm/vm_fault.c>
  (`vm_page_map_and_validate_cs`), and the same files in `xnu-6153.141.1` (Catalina) and
  `xnu-12377.121.6` (Tahoe) for the version differences.
