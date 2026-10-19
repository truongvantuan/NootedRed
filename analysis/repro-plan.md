# NootedRed #158 — evidence snapshot & safe reproduction plan

> **Task**: `task-4` (repro-evidence) of the AMDRenoir Chromium/OpenGL investigation.
> **Snapshot taken**: 2026-10-18 ~21:20 (+08:00), macOS 15.8.1 (24H32), AMD Renoir
> `1002:1638`, NootedRed 0.9.0 + Lilu 1.7.2 loaded.
> **Scope**: (A) latest upstream/community evidence for issue #158; (B) a safe,
> offscreen reproduction harness and a procedure for testing candidate user-space
> patches later. This document separates **verified facts**, **community claims**
> and **speculation**; see §6 for the consolidated table.

## TL;DR (中文摘要)

- **上游没有修复**：`ChefKissInc/NootedRed` master 仍停 `9ff85a6`（2026-10-10），无
  相关分支/PR/tag；#158 最后维护者发言是 **2026-07-13**：「可能找到方案，但未测试、
  也还无法正确实现」，配图正是 `gfx9_HwInfoInitData` 把 iGPU 当 Vega 独显（写死
  `gpuFamily=0x8d` 等）的反编译。
- **社区已有“概念验证级”实现**：fork `steve12311/NootedRed`（2026-10-07，领先上游
  7 个提交）在 NootedRed 里实现了**用户态驱动补丁器**（hook 内核
  `_shared_region_check_np`，只改进程私有 COW 页），其中 **LegacyBlend** 补丁把
  RB+ 能力分支的 `74 28` 改成 `90 90`，强制对 iGPU 设置
  `CB_COLOR_CONTROL.DISABLE_DUAL_QUAD`。作者文档称有 Ryzen 7 5800H（Cezanne）用户
  实测修好 Chrome 花屏/碎屏；但其门槛是 **macOS 26 / Darwin 25**，不能直接用于本机
  15.8.1。这是“这条路可行”的最强旁证，但不是可用成品。
- **本机正在复现该 bug**：`/Library/Logs/DiagnosticReports` 中 2026-10-18
  21:12–21:17 有 **13 个 `*.gpuRestart`**（WindowServer 与 **DeepSeek Harness**
  Electron 触发，Signature 1/2，channel 13/23 GFX，`DID=0x1638`）；同时两个最小
  CGL/FBO 测试程序（`glblend2`、`glblend4`）在**第一次 `glClear()`** 时以完全相同的
  栈 SIGSEGV 于 `AMDRadeonX5000GLDriver`。已确认：**仅创建上下文 + `glGetString`
  安全；`glClear`/绘制不安全**。
- **安全复现工具已就绪**：`tools/gl_blend_probe.c` + `tools/build.sh`（编译通过，
  位于 `build/tools/gl_blend_probe`），三种模式 `--inspect`（安全，已运行）、
  `--link`（不提交绘制，已运行）、`--render`（高风险，**未运行**，需 Lead 批准）。
  基线结果：`GL_VERSION 4.1 ATI-7.0.25`，`GL_ARB_blend_func_extended` **present**、
  `GL_EXT_blend_func_extended` **MISSING**，`GL_MAX_DUAL_SOURCE_DRAW_BUFFERS=1`，
  双源 shader 能链接且 `c1` 绑定 index 1。
- **建议**：先用离线反汇编/二进制比对（无需 GPU）确定 15.8.1 的 `gfx9_HwInfoInitData`
  与双源混合分支补丁点；任何真机 GL 绘制测试前先重启到干净状态，并按 §4.6 的阶梯
  由 Lead 逐级批准；候选补丁先走 §4.7 的**进程内、仅本进程 COW 自补丁**方案验证，
  再考虑进入 NootedRed 内核 UserPatcher（fork 路线）。

---

## 0. Bottom line

| Question | Answer | Confidence |
| --- | --- | --- |
| Is there an upstream fix / branch / PR for #158? | **No.** master `9ff85a6` (2026-10-10), single branch, 46 PRs are dependency/docs only. | verified |
| Latest maintainer statement? | **2026-07-13**: “potentially found a solution… haven't tested it yet, and still can't implement it properly”; screenshot of `gfx9_HwInfoInitData` hardcoding Vega values. | verified |
| Any public implementation of a fix? | **Yes, one serious fork** `steve12311/NootedRed` (user-space COW page patcher + `-NRedLegacyBlend` dual-quad fix); gated to macOS 26. Plus two fresh BFixup forks (workaround, not a fix). | verified repo content; hardware effect is a community claim |
| Any KB/community workaround that is verified? | BFixup (lower reported GL version; maintainer discourages), ANGLE OpenGL + `disableBlendFuncExtended` (maintainer), disable HW acceleration (per-app), VRAM ≥2 GB; for #235: `allowMetalTransferSession NO`. | verified statements |
| Can we reproduce locally? | **Yes, already happened on this boot**: 13 `*.gpuRestart` (WindowServer/DeepSeek Harness) plus two minimal probe SIGSEGVs in `AMDRadeonX5000GLDriver`. | verified |
| Is offscreen GL rendering safe on this box? | **No.** A minimal FBO `glClear()` without a drawable crashes the driver and coincides with GPU resets. Context creation + `glGetString` are OK. | verified |
| Where exactly to patch the GL driver for 15.8.1? | Not determined here (task-1/task-2 territory). The fork’s Metal-driver `LegacyBlend` is the closest pointer: NOP the RB+ capability branch so `DISABLE_DUAL_QUAD` is programmed on iGPU. | speculation, strongly supported |

---

## 1. Environment under test

| Item | Value | Source |
| --- | --- | --- |
| OS | macOS 15.8.1 (24H32), Darwin 24.x | `sw_vers` |
| CPU / iGPU | AMD Ryzen 7 5800U; Radeon RX Renoir Graphics, `1002:1638`, RID `0xc1`, ROM `113-CEZANNE-021`, VRAM 2 GB | `system_profiler SPDisplaysDataType` |
| Kexts | `org.ChefKiss.NootedRed 0.9.0`, `as.vit9696.Lilu 1.7.2`, `AMDRadeonX5000` / `X5000HWLibs` / `X5000HWServices` 7.0.0, `X6000Framebuffer` 7.0.0 | `kmutil showloaded` |
| GL driver | `AMDRadeonX5000GLDriver` **7.0.25**, bundle on disk at `/System/Library/Extensions/AMDRadeonX5000GLDriver.bundle/Contents/MacOS/AMDRadeonX5000GLDriver` (1,808,640 B, Mach-O x86_64h, mtime 2025-09-23) | `defaults read …/Info.plist`, `file`, `ls` |
| Shared cache | `/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld/dyld_shared_cache_x86_64h*` (~2.4 GB total); its image table contains `AMDRadeonX5000GLDriver` and `GLEngine` path strings | `grep -a` on the cache files |
| SIP | `Custom Configuration`: kext signing disabled, **Filesystem Protections enabled**, debugging restrictions enabled (`csrutil status`) | |
| Electron apps installed | `123云盘.app`, `DeepSeek Harness.app`, `Obsidian.app`, `Tabby.app`, `WorkBuddy.app`, `ZCode.app`, `balenaEtcher.app`, `哔哩哔哩.app` (all contain `Electron Framework.framework`). **No Chrome/Chromium**; `Zen.app` is Firefox-based | filesystem scan |
| GL toolchain | Apple clang 17.0.0, SDK `MacOSX26.2` (OpenGL.framework still present, deprecated), SDL3 + sdl2-compat via Homebrew; no GLFW/GLEW/glxinfo | `xcrun clang --version`, SDK listing, `brew list` |

> Note: the machine has clearly been rebooted shortly before this snapshot (GPU
> restart reports say “Uptime 0:24:02…”, i.e. the boot happened around 20:48).

---

## 2. How this evidence was gathered

- GitHub REST/GraphQL via the authenticated `gh` CLI (5,000 req/h) and raw `curl`
  against `api.github.com` for the anonymous endpoints: issue #158 body + all 114
  comments, issue #235 body + all 292 comments, timelines, `marked_as_duplicate`
  events, repository branches/tags/commits/PRs, 1,284 forks (top pages), code &
  commit search.
- Local: `~/Library/Logs/DiagnosticReports`, `/Library/Logs/DiagnosticReports`,
  `sw_vers`/`system_profiler`/`kmutil`, `nm`, `strings`, `otool`, `defaults`,
  `csrutil`; `/tmp` probe artifacts left by earlier (concurrent) probe runs were
  read but **not produced by this task**.
- Reading the prior in-repo report `Chromium-OpenGL-Issue-Report.md`
  (2026-10-15) as *prior AI output*: its §4–§9 static analysis and its hypothesis
  “level B = clear the RB+ capability bit” are consistent with what was found in
  the fork (see §3.7.1), but were not independently re-verified here beyond the
  symbol/string checks in §3.8.
- **Could not do inside this sandboxed session**: `log show` (“log: Cannot run
  while sandboxed”) and `ps`/`/bin/ps` (“Operation not permitted”). Crash/GPU-reset
  files and `kmutil`/`sysctl` were used instead.

---

# Part A — Evidence

## 3.1 Issue #158 at a glance

- URL: <https://github.com/ChefKissInc/NootedRed/issues/158>
- Title: *“Blend shader functions cause corruption, freezes or crashes”*
- Opened **2023-09-06** by `VisualEhrmanntraut` (maintainer), label `OS/All`,
  state **open**, **114 comments** at fetch time, last comment
  **2026-07-13T10:22:01Z**.
- Body (verbatim, shortened): *“Software like Chrome and Sublime Text 4 can cause
  corruption and freezes. To Reproduce: Open software which uses dual source blend
  like Chrome and Sublime Text 4. Observe.”* + one screenshot.
- The first comment (2023-09-06) is the maintainer’s `AlEhrmanntraut`-quoted note
  that on their PC Minecraft must be started 4 times before it works.

## 3.2 Maintainer statements (chronological, verified)

All comments are `author_association: MEMBER` and authored `VisualEhrmanntraut`
unless noted. Permalinks use the `issuecomment-` id.

| Date (UTC) | Permalink | Statement (quote / paraphrase) |
| --- | --- | --- |
| 2023-11-11T23:08:08Z | [#issuecomment-1806939696](https://github.com/ChefKissInc/NootedRed/issues/158#issuecomment-1806939696) | “in `AMDRadeonX5000GLDriver`, function `_gfx9_HwInfoInitData` and `_amdUbm_HWL_Init`, … the device family is **hardcoded instead of being read from the accelerator**.” |
| 2023-12-10T13:39:13Z | [#issuecomment-1848968492](https://github.com/ChefKissInc/NootedRed/issues/158#issuecomment-1848968492) | On BFixup: “I do not recommend using this hack kext because it just lowers the OpenGL version, which works around some dysfunctional OGL extensions… The goal of this issue is to track progress finding and resolving the underlying issue, not working around it.” |
| 2024-06-16T01:32:29Z | [#issuecomment-2171004119](https://github.com/ChefKissInc/NootedRed/issues/158#issuecomment-2171004119) | “I have fixed almost all the issues” (Catalina tests; screenshots; subsequent comment 2024-06-21: “I never committed the changes”). |
| 2024-06-27T10:27:57Z | [#issuecomment-2194334941](https://github.com/ChefKissInc/NootedRed/issues/158#issuecomment-2194334941) | “There is no fix available, neither is a fix easy due to the design of Lilu. I am planning to make a Lilu replacement before I try to actually fix it.” |
| 2024-06-27T10:33:32Z | [#issuecomment-2194344009](https://github.com/ChefKissInc/NootedRed/issues/158#issuecomment-2194344009) | multiple root causes; also has to remove “that last bit that I currently steal from the navi drivers” **and** fix user-space code. |
| 2024-08-25T15:42:01Z | [#issuecomment-2308900749](https://github.com/ChefKissInc/NootedRed/issues/158#issuecomment-2308900749) | “We have found what causes the corruption; it's **dual source blend**. Switching ANGLE to OpenGL and ANGLE feature flags to `disableBlendFuncExtended` fixes the corruption… EDIT: Not always. It seems to be **blending functions in general** that are problematic.” |
| 2025-03-02T23:17:36Z | [#issuecomment-2692960734](https://github.com/ChefKissInc/NootedRed/issues/158#issuecomment-2692960734) | “To resolve this issue **user-space patches are needed**, more complex ones than you can do with Lilu… Lilu user-space patching causes issues anyways, like app crashes and system instability. I will make an announcement…” (the announcement is org discussion #1, §3.7.3). |
| **2026-07-13T09:15:42Z** | [#issuecomment-4956347445](https://github.com/ChefKissInc/NootedRed/issues/158#issuecomment-4956347445) | **“Hello everyone. I have potentially found a solution. Don't get too excited: I haven't tested it yet, and still can't implement it properly as stated previously.”** |
| **2026-07-13T10:22:01Z** | [#issuecomment-4956933150](https://github.com/ChefKissInc/NootedRed/issues/158#issuecomment-4956933150) | **“The problem is functions like the one pictured below; no logic to handle the iGPUs, thus using Vega dGPU values hereby, in theory, causing this and possibly also #235.”** + screenshot (below). |

The 2026-07-13 screenshot was downloaded and inspected. It is a decompiler view of:

```c
void gfx9_HwInfoInitData(struct GFX9_HwInfoRec* hwInfo, _sAMD_GET_HW_INFO_VALUES* arg2, uint32_t arg3)
...
    hwInfo->chip.isVega10 = isVega10 | 0x40;
    if (r9 <= 0x13) {          // family-based hardcoded Vega values
        hwInfo->common.gpuFamily          = 0x8d;
        hwInfo->common.numShaderEngines   = 4;
        hwInfo->common.numShaderArrays    = 1;
        hwInfo->common.numGsWavesPerVGT   = 0x20;
        hwInfo->common.numOffChipLdsBuffersPerSE = 0x7f;
        hwInfo->common.numParameterCacheLines     = 0x1000;
        hwInfo->common.numTCC             = 0x10;
        hwInfo->chip.isVega10             = isVega10 | 0xc1;
    } else if (r9 <= 0x27) { ...0x8d,4,1,0x20,0x80,0x1000,8, isVega10|0xc2... }
    ...
hwInfo->common.totalNumComputeUnits = rax_24.d * numShaderEngines * numShaderArrays;
```

This is the maintainer’s own evidence for “iGPU handled by Vega dGPU values”.
(The image is GitHub-hosted:
`https://github.com/user-attachments/assets/3f6a87bf-0a58-440f-b198-502563eb8629`.)

**After 2026-07-13** the issue has no further comments. The timeline does show
later bookkeeping only: `marked_as_duplicate` events on 2026-07-16, 2026-08-10,
2026-08-15 (10 duplicates in total, §3.5) and a cross-reference to #435
(2026-07-23). GitHub issue search for issues created after 2026-07-01 containing
`OpenGL`, `blend` or `chromium` returns **0 results**. So the “latest maintainer
statement after 2026-07” is exactly the two 2026-07-13 comments above: a
*hypothesis with no implementation*.

## 3.3 What is *not* in #158 (checked, verified)

- No branch/commit/PR linked from #158 that implements HwInfo or dual-quad fixes.
- No `HwInfoInitData` patch data, no user-space patch framework announced as
  usable in the repo.
- The 2026-07-13 image is the only concrete technical pointer in the last year.

## 3.4 Issue #235 and its verified workaround

- URL: <https://github.com/ChefKissInc/NootedRed/issues/235>
- Title: *“[Sonoma+] Specific compute tasks (like from the Wallpaper decoding) may hang”*
- Opened 2024-03-13 by `darthsian`; open; labels `OS/Sonoma`, `OS/Sequoia`,
  `OS/Tahoe`, `Status/TriageRequired`; **292 comments**; last comment
  2026-06-06T22:19:53Z. Body contains a maintainer CAUTION note pointing at
  `#issuecomment-4567109847`.
- Root cause discussed: VideoToolbox’s `VTMTSComputeFunction` compute path
  (`VideoToolbox Metal Transfer Session Compute Function`) and GFXOff/power-gating
  races on Renoir/Cezanne; huge serial-log/compute-queue analysis by the
  maintainer in May 2026.
- **Verified workaround** (maintainer, 2026-05-28T18:33:55Z,
  [#issuecomment-4567109847](https://github.com/ChefKissInc/NootedRed/issues/235#issuecomment-4567109847)):

  ```sh
  # already booted:
  sudo defaults write /Library/Preferences/com.apple.coremedia allowMetalTransferSession -bool NO
  sudo chmod 644 /Library/Preferences/com.apple.coremedia.plist
  # reboot
  # (recovery variant: defaults write "/Volumes/Macintosh HD/Library/Preferences/com.apple.coremedia" ...)
  ```

  Later comments confirm it worked for setup-assistant/Wallpaper/Weather hangs
  and that GFXOff can stay enabled once the Metal transfer session is disabled.
- Also mentioned: 0.9.0 test builds with a “compute GFXOff workaround for Raven”
  (2026-06-02 attachments), firmware updates, and the unresolved Renoir behaviour.
- **Relation to #158** is only the maintainer’s 2026-07-13 phrase “possibly also
  #235”; the two issues have *different* triggers (blend/GL vs compute/Metal
  transfer). Do **not** use the `allowMetalTransferSession` workaround as evidence
  for a #158 fix.

## 3.5 Duplicates, known triggers, workarounds

GitHub’s REST timeline does not expose the canonical issue for
`marked_as_duplicate` events, but GraphQL confirms all 10 `MarkedAsDuplicateEvent`
entries on #158’s timeline point at **issue #158** itself. Mapping them to issue
numbers by `closed_at` (9 exact, 1 within ±1 s) yields these **closed as duplicate
of #158**:

| Duplicate | Closed (UTC) | Title |
| --- | --- | --- |
| #446 | 2026-08-15 | Zen browser screen corruption on a specific website |
| #435 | 2026-08-10 | `[Tahoe]` Gray bars appearing in Safari |
| #440 | 2026-07-16 | Flickering during graphics-intensive tasks (games) — Tahoe 26.5.2 |
| #393 | 2025-11-18 | Crash screen when using Cursor on Sequoia |
| #384 | 2025-09-29 | Graphical artifacts in Safari under high GPU intensity |
| #375 | 2025-07-19 | Webview in Git Credential Manager crashes |
| #363 | 2025-05-23 | System freezing |
| #355 | 2025-04-04 | Discord and Visual Studio Code not running properly |
| #340 | 2025-02-17 | Wine crashes with GPU errors on Vega 8 |
| #299 | 2025-03-02 | Frequent WindowServer crashes |

Issues cross-referenced from #158 but *not* marked as its duplicates (often fixed
or closed for other reasons): #165 (Firefox crash), #187, #198, #200 (alacritty),
#203 (VRAM 1–2 GB), #209 (balenaEtcher hang), #233 (Java GUI), #241 (Twitter 2FA),
#247 (artifacts), #307, #311, #391, plus #65/#192 links. #235 is separate.

**Triggers reported by users** (from #158/#235 comments; not independently
reproduced): Chrome/Edge/Arc/Discord/VS Code/Cursor/YouTube Music/Zen (Chromium,
hence ANGLE), Sublime Text 4 / Sublime Merge 2, Firefox WebGL (e.g. canva.com,
arstechnica), Blender, DOSBox `output=opengl`, Godot, League of Legends client,
Minecraft (for some users works fine), the Apple TV site, and notion.com.

**Workarounds reported / recommended**:

| Workaround | Evidence | Status |
| --- | --- | --- |
| Disable Chromium hardware acceleration / use `--disable-gpu`-style flags | many comments; maintainer suggests nothing else for Chrome pre-2024 | effective but loses acceleration |
| Use Safari / Firefox (Firefox with WebGL disabled if needed) | maintainer repeatedly | effective for browsing; Firefox can still crash on some sites |
| ANGLE → OpenGL backend + `disableBlendFuncExtended` ANGLE feature flag | maintainer 2024-08-25 | worked “not always”; per-app |
| VRAM > ~1 GB (2–3 GB) | user reports (2023-12, 2024-05) | mitigates, not a fix |
| `BFixup.kext` (lower reported GL version via dyld/shared-cache patch) | source attached to #158; maintainer 2023-12-10 does **not** recommend | workaround, can disable acceleration entirely; user-space patching side effects (§3.7.3) |
| `allowMetalTransferSession NO` | maintainer 2026-05-28, for **#235** compute hangs | verified for #235; unrelated to dual-source blend |

## 3.6 Upstream repository state (verified through the GitHub API)

- `ChefKissInc/NootedRed` — default branch `master`, **tip `9ff85a6`**
  “Forgot to update the copyright year in the Info.plist” (2026-10-10), 1,984
  stars, 1,275 forks, 19 open issues; the local checkout matches the remote tip.
- `git ls-remote` shows **only `refs/heads/master`**; tags end at `v0.8.9`/`v0.8.10`
  (CHANGELOG: v0.8.10 dated 2026-05-15). No `-NRedGLFix` branch, no user-space
  patch branch.
- 46 PRs total; every recent one is a Dependabot/actions bump or docs (“Bump
  actions/*”, “Update README.md”); nothing GL/user-space related.
- Code search in the repo: `gfx9_HwInfoInitData` / `HwInfoInitData` / `BFixup` /
  `blend_func_extended` / `NRedLegacyBlend` → **no matches**. Commit search for
  `HwInfoInitData`, `gfx9_HwInfoInitData`, `blend_func_extended` → **0**.
- Issues search for `dual source blend` in the repo → only #158.
- Conclusion: **there is no upstream implementation, work-in-progress branch or
  unreleased tag to adopt as of 2026-10-18.**

## 3.7 Community implementations

### 3.7.1 `steve12311/NootedRed` — a real user-space patcher (most important find)

- URL: <https://github.com/steve12311/NootedRed> (fork created **2026-10-04**,
  last push **2026-10-07T04:48:41Z**; owner `steve12311` / “菌菌”, Chengdu;
  GitHub compare: **7 commits ahead, 5 behind** upstream master; 1 fork,
  `Brucelaw0327/NootedRed`).
- Added files (from `compare/master...steve12311:master`):
  `NootedRed/UserSurfaceSync.cpp/.hpp`, `UserSurfaceSyncResolver.hpp`,
  `UserSurfaceSyncData.hpp` (3,307 lines of generated patch data),
  `UserSharedCache.hpp`, `UserCacheResolver.hpp`, `UserVideoDecode*`,
  `VCN*`, `docs/metal-rendering-fix.md`, `docs/vega-tahoe-r3-test.md`,
  `docs/user-cache-dynamic.md`, `docs/vcn.md`, and an extensive `tools/` suite
  (`build_surface_sync_patch.py`, `test_legacy_blend_gate.py`,
  `test_metal_dual_source.m`, …). `NRed.cpp`/`X5000.cpp` are only minimally
  touched (+7/-0 and +20/-8).
- Commit series (2026-10-02 → 2026-10-07):
  `X5000: Fix Cezanne accelerated rendering` → `VCN: Add experimental Cezanne
  hardware decoding` → `UserSurfaceSync: Support Vega APUs and compatible Tahoe
  caches` → `VCN: Generalize VCN2 APU capability matching` → `VCN: Match Tahoe
  with native kernel version constants` → **`UserPatches: Share dynamic cache
  resolution`** → `VCN: Fix hardware encode feedback and source pitch`.
- **Mechanism** (read from source): it is *not* Lilu `UserPatcher`. It hooks the
  kernel symbol **`_shared_region_check_np`** (`KernelPatcher::routeMultipleLong`),
  then, for the target process, walks its `vm_map`
  (`_get_task_map`, `_mach_vm_region_recurse`), validates the process’s actual
  dyld-cache UUID, locates the `AMDRadeonX5000MTLDriver` image and the exact
  functions by **full function-content SHA-256**, `mach_vm_protect`s the target
  pages to writable, writes the patches with `copyout`, then restores the
  original protection. It only writes **process-private COW pages** (never the
  on-disk cache, never the file) and rolls back on any partial failure. It gates
  on PCI ID (`0x15D8, 0x15DD, 0x15E7, 0x1636, 0x1638, 0x164C`) and on
  **Darwin 25 (macOS 26)**: `if (!currentKernelVersion().majorMatches(MACOS_26))
  { …Rejected=4; return; }`.
- **LegacyBlend** (the #158-relevant part) — from
  `docs/metal-rendering-fix.md` (translated):
  *“LegacyBlend fixes the RB+ capability branch in pipeline construction: when
  the capability report is missing, it still computes
  `dualSource || !allowRBPlus` and correctly sets
  `CB_COLOR_CONTROL.DISABLE_DUAL_QUAD`.”* Generated patch data
  (`UserSurfaceSyncData.hpp`) shows exactly:

  ```c
  inline constexpr UInt8 BlendGateOriginal[] = { 0x74, 0x28 };   // je +0x28
  inline constexpr UInt8 BlendGatePatched[]  = { 0x90, 0x90 };   // nop; nop
  inline constexpr Patch LegacyBlendPatches[] = {
      {0x310D71A28ULL, Original0, SrdSharedPatched0, sizeof(Original0)},
      {0x310D71AFFULL, Original1, SrdSharedPatched1, sizeof(Original1)},
      {0x310C77708ULL, BlendGateOriginal, BlendGatePatched, sizeof(BlendGateOriginal)},
  };
  ```

  i.e. remove the conditional jump around the dual-quad-disabling store, so the
  iGPU always programs `DISABLE_DUAL_QUAD`. The other two patches are the
  Metal-rendering “immediate sync / shared SRD” fixes (separate from #158).
  `test_legacy_blend_gate.py` executes the real pre-patch function on a page and
  asserts 1024 randomized cases: original sets the bit only when
  `hardware && (dual || !rbPlusEnabled)`, patched sets it when
  `dual || !rbPlusEnabled` regardless of the hardware flag — a precise
  description of the intended behavior change.
- **Boot args**: `-NRedImmediateSync`, `-NRedSrdShared`, `-NRedLegacyBlend`,
  `-NRedComputeScratch` (documented in `docs/metal-rendering-fix.md`; diagnostic
  IORegistry properties such as `NRedLegacyBlendEnabled/Applied/WindowServerPID`).
- **Claimed validation** (community claim, *not independent*): the docs state a
  user on **Ryzen 7 5800H (Cezanne, also a supported `0x1638`-family APU)**
  confirmed LegacyBlend fixes WeChat and Chrome 花屏/碎屏; the docs are explicit
  that the patch is gated to exact driver function contents and that “real
  another-cache / target-boot / Chromium-Discord effect still need hardware
  acceptance”. It also warns: *“原生 Metal 最小测试也曾在双源混合时产生像素差异并
  破坏桌面”* — a native Metal dual-source test produced pixel differences and
  broke the desktop on their machine (relevant to our safety plan: **do not** run
  render tests casually).
- **Why this matters**: it is a working existence proof that (a) the dual-quad /
  RB+ branch is the actionable fix point for #158-class corruption, and (b) a
  kernel-supported, process-scoped, content-validated COW page patcher can apply
  user-space driver fixes without modifying the system installation. **It does
  not solve our machine directly**: it patches `AMDRadeonX5000MTLDriver`
  (Metal), not `AMDRadeonX5000GLDriver` (the driver in #158’s crash stack), and
  it is deliberately rejected on Darwin 24 (macOS 15.8.1). Its cache offsets
  (`0x310C77708`, …) are for a different macOS build/UUID.

### 3.7.2 BFixup (workaround) — source verified

- Original attachments in #158: `BFixup-master.zip` / `BFixup.kext.zip`
  (2023-12-06, and re-uploads 2023-12-06 by `moqsien`), links in
  [#issuecomment-1842011907](https://github.com/ChefKissInc/NootedRed/issues/158#issuecomment-1842011907).
  The zip was downloaded and inspected.
- `BFixup/kern_start.cpp` (MIT, osy base): a Lilu plugin that hooks kernel
  **`_cs_validate_page`**, and for pages whose path satisfies
  `UserPatcher::matchSharedCachePath(path)` does `findAndReplace` with:
  - Monterey: `8B 45 E0 B9 01 00 04 48 89 C2 21 CA 39 CA 75 4E` →
    same with `EB 4E` (jmp instead of jne) — `AddrLib::GetBaseArrayMode`
    return branch;
  - Ventura 13.3: `… 0F 85 A0 00 00 00` → `… E9 A1 00 00 00 90`.
  Plugin configuration: `KernelVersion::BigSur` … `KernelVersion::Sonoma`; the
  maintainer’s description is “patches the dyld to force GLEngine to report a
  lower OpenGL version”.
- Maintainer assessment: not recommended (2023-12-10); it lowers the reported GL
  version and can even disable hardware acceleration for some apps. Multiple
  users report boot failures/instability with it (e.g. 2023-12-08 comments).
- Two **fresh** forks appeared during this investigation (both unverified):
  - `hoaug-tran/BFixup` (<https://github.com/hoaug-tran/BFixup>, created
    **2026-10-16**, README claims “modern Lilu routing API
    (`routeMultipleLong`/`RouteRequest`)”, Sequoia support, Lilu ≥ 1.7.2,
    null-checks, error logging; 1 star, 3 commits, no hardware reports);
  - `macintelk/BFixup` (<https://github.com/macintelk/BFixup>, created
    **2026-10-15**, initial commit only).
  Treat both as **unvalidated community code**; they are workarounds (GL version
  lowering), not the root fix.

### 3.7.3 Maintainer PSA: user-space patching is harmful (why NootedRed ships none)

Org discussion #1, *“IMPORTANT PSA about Lilu user-space patching kexts such as
RestrictEvents”*, **2025-03-03**:
<https://github.com/orgs/ChefKissInc/discussions/1>. Key facts from the post:

- user-space patching kexts caused app crashes and system instability, worse on
  Ventura/Sequoia; disabling them brought “a significant speedup and improved
  stability”;
- it is “also the cause of those sporadic APFS ‘Volume Hash Mismatch’
  notifications” and of software updates not installing/appearing;
- a non-exhaustive list: RestrictEvents, BlueToolFixup, FeatureUnlock, NoTouchID,
  IMKLPatcher, **BFixup**; advice: avoid them, or minimise.

This is the announcement referenced by the maintainer in #158 on 2025-03-02. Any
NootedRed-integrated user-space patch (fork route) must be evaluated against this
explicit warning: the maintainer considers this class of patching unsafe by
design, which is why the 2026-07-13 “solution” remains unimplemented.

### 3.7.4 Other leads checked (no fix found)

- `icex/macos-raphael-igpu` research repo — file
  `findings/research/transparency-live-composition-20260916.md` (2026-09-16)
  mentions `Apple gfx10_HwInfoInitData derives hwinfo+0xac = min(numSE*512-1,1023)`
  and a parameter-cache (`GE_PC_ALLOC`) hypothesis. It is a different GPU
  (Raphael `gfx1030`), different stack (Metal/NSVisualEffectView transparency)
  and explicitly says the clamp is “not established as the visual root cause;
  do not ship”. Useful context for HwInfo fields, **not** a #158 fix.
- Maintainer’s “Lilu replacement” (announced 2024-06-27): no public repository
  found on `VisualEhrmanntraut` or `ChefKissInc` as of 2026-10-18; org repos are
  NootedRed, NootRX, Inferno, ForgedInvariant, SMCRadeonSensors, PanicInfoReader,
  DiskDbg, PlistOxide, website/.github. Status: **not shipped**.
- Fork sweep: 1,284 forks; recently pushed / non-trivial ones (`OscarrWu`,
  `tyglll`, `laobamac`, `davincee`, `Necorupt`, `Eliksey`, `OscarrWu` branches
  `a2-fboffset-from-apple`, `p7d-prime`) show unrelated or WIP work; commit/code
  search for `HwInfoInitData`, `gfx9_HwInfoInitData`, `blend_func_extended` found
  nothing except the fork above and generic Mesa/ANGLE code. No other public fix.

## 3.8 Local evidence (this machine, this boot)

All times +08:00. Collected 2026-10-18 ~21:09–21:22.

### 3.8.1 GPU resets (issue #158 reproducing live)

`/Library/Logs/DiagnosticReports/` contained **13 `Kernel_*.gpuRestart`** files
from this boot (newest at 21:17:36):

| Time | Application | Signature | Restart channel | Uptime |
| --- | --- | --- | --- | --- |
| 21:12:30 | WindowServer | 2 | 23 GFX | 0:24:02 |
| 21:12:41 | WindowServer | 1 | 23 GFX | 0:24:10 |
| 21:12:56 | WindowServer | 2 | 23 GFX | 0:24:29 |
| 21:13:08 | WindowServer | 2 | 23 GFX | 0:24:40 |
| 21:14:52 | WindowServer | 1 | 23 GFX | 0:26:25 |
| 21:15:03 | DeepSeek Harness | 1 | 13 GFX | 0:26:32 |
| 21:15:13 | WindowServer | 2 | 23 GFX | 0:26:39 |
| 21:15:14 | WindowServer | 2 | 23 GFX | 0:26:46 |
| 21:15:44 | WindowServer | 2 | 23 GFX | 0:27:09 |
| 21:16:04 | **DeepSeek Harness** | 2 | 13 GFX | 0:27:33 |
| 21:16:35 | WindowServer | 2 | 23 GFX | 0:28:01 |
| 21:17:15 | DeepSeek Harness | 2 | 13 GFX | 0:28:41 |
| 21:17:36 | DeepSeek Harness | 1 | 13 GFX | 0:29:07 |

Common header (verified):

```
Graphics Hardware:   AMD Radeon RX Renoir Graphics
AMDRadeonX5000_AMDVega10GraphicsAccelerator state: ENABLED
 PCIe Device: [4:0:0], DID=0x1638, RID=0xc1, SSID=0x1536
 TotalVideoRAMBytes: 0x0000000080000000 (2147483648)
Signature: 1 or 2     Restart Channel: 13 GFX / 23 GFX
VM Protection Fault (GFX) status:
    Page GPUAddress = 0x…, VMID = 1, R/W = RD
```

Interpretation: the iGPU is being driven by
`AMDRadeonX5000_AMDVega10GraphicsAccelerator`; WindowServer and an **Electron
app** (DeepSeek Harness — the GUI hosting this very session) both triggered GPU
resets in a 5-minute window. This is exactly the failure class of #158/#235 and
is the local reproduction, independent of any synthetic test.

> Timing caveat: at least some of these resets overlap with probe runs performed
> by a concurrent/earlier process (`/tmp/glblend*` artifacts, see §3.8.2), so they
> may be *aggravated* by those probes. The Electron-app-triggered ones (21:15:03,
> 21:16:04, 21:17:15, 21:17:36) are the least ambiguous.

### 3.8.2 Minimal-probe crashes (the safety lesson)

`~/Library/Logs/DiagnosticReports/`:

- `glblend2-2026-10-18-211253.ips` (21:12:53) — `EXC_BAD_ACCESS`/SIGSEGV,
  `KERN_INVALID_ADDRESS at 0xb553ff9d`, process `glblend2` (a minimal CGL/FBO
  probe; source left at `/tmp/glblend2.c` by a concurrent process):
  ```
  AMDRadeonX5000GLDriver +24178   glrAMD_GFX9_UpdateHwExportBlockState
  AMDRadeonX5000GLDriver +394190  glrAMD_GFX9_UpdateDrawBufferInfo
  AMDRadeonX5000GLDriver +394793  glrATI_Hwl_DrawableChanged
  AMDRadeonX5000GLDriver +98700   glrBindContextDrawFramebuffer
  libGPUSupportMercury +17137     gldUpdateDrawFramebuffer
  GLEngine +856535                gleUpdateDrawFramebufferState
  GLEngine +121069                glClear_Exec
  glblend2 +2531                  main
  ```
- `glblend4-2026-10-18-211622.ips` (21:16:22) — **identical stack**, different
  fault address (`0xbbbfcfdd`). Two independent minimal probes crash at the very
  first `glClear()`.
- `glblend3.c` and other `/tmp` probes exist (21:12–21:13); the recurring failure
  mode is the same.

**Conclusion**: a CGL context without a **valid drawable** + `glClear` is enough
to SIGSEGV inside the user-space driver and to coincide with GPU resets. The
crash happens in the draw-framebuffer update path, not in the blend path, but the
hardware/driver state abuse is the same class as #158. This is why the harness in
§4 never clears/draws without a PBuffer drawable and why all render probing is
approval-gated.

### 3.8.3 Driver binary facts (corroborate #158’s root cause)

`nm -a` on the on-disk bundle shows the functions the maintainer refers to:

```
000000000000df40 t _gfx9_HwInfoInitData
0000000000009d37 t _glrAMD_GFX9_UpdateHwBlendColorState
0000000000008134 t _glrAMD_GFX9_UpdateHwCbDualQuadMode
0000000000007f62 t _glrAMD_GFX9_UpdateHwBlendOptState
00000000000083e3 t _glrAMD_GFX9_UpdateHwBlendState
0000000000005cb9 t _glrAMD_GFX9_UpdateHwExportBlockState
00000000000605c8 t _glrATI_Hwl_DrawableChanged
0000000000018135 t _glrBindContextDrawFramebuffer
```

- `strings` lists only **Vega dGPU** renderer names (`Radeon RX Vega 56/64`,
  `Radeon Pro Vega 16/20/48/56/64/64X`, `Vega10 … Prototype`), consistent with
  “the GL driver is a Vega dGPU driver that NootedRed makes the iGPU bind into”.
- The string `blend_func_extended` is **not** present in the driver; extensions
  are synthesised by GLEngine at runtime (see runtime result in §4.3).
- The bundle and the shared cache both contain `AMDRadeonX5000GLDriver`; the
  shared cache (`…/Cryptexes/OS/System/Library/dyld/dyld_shared_cache_x86_64h*`)
  is the likely mapping source for processes. This matters for patch route
  selection (§4.7).

### 3.8.4 Runtime GL facts (safe inspect; see §4.3 for exact output)

`GL_RENDERER = AMD Radeon RX Renoir Graphics OpenGL Engine`,
`GL_VERSION = 4.1 ATI-7.0.25`, `GL_VENDOR = ATI Technologies Inc.`,
`GL_ARB_blend_func_extended` present, `GL_EXT_blend_func_extended` missing,
`GL_MAX_DUAL_SOURCE_DRAW_BUFFERS = 1`, 46 extensions, dual-source shaders link
and `c1` binds to frag-data index 1. This independently confirms the 2023-12-10
GLEW observation in #158 (ARB present / EXT missing) on this macOS build.

### 3.8.5 Electron apps usable for app-level reproduction

No Chrome/Chromium is installed. The Electron apps above can be used for a
controlled app-level test later (per-app, with explicit approval): `ZCode`
(`dev.zcode.app`, has `ElectronAsarIntegrity`), `Obsidian` (`md.obsidian`),
`DeepSeek Harness` (`com.deepseek.dsh`, currently already triggering GPU resets),
`Tabby`, `WorkBuddy`, `123云盘`, `balenaEtcher`, `哔哩哔哩`.

---

# Part B — Safe reproduction plan

## 4.1 Toolchain inventory (verified)

| Item | Availability | Notes |
| --- | --- | --- |
| `xcrun clang` | Apple clang 17.0.0, target `x86_64-apple-darwin24.6.0` | builds the harness |
| SDK | `MacOSX26.2` at `/Applications/Xcode.app/…/MacOSX.sdk` | `OpenGL.framework` headers still present (deprecated) |
| `CGL` + `OpenGL` framework | present; includes `CGLCreatePBuffer`/`CGLSetPBuffer` (declared deprecated 10.7 but linkable) | used for the offscreen path |
| GLFW / GLEW / glxinfo | **not installed** | not needed |
| SDL3, sdl2-compat | installed via Homebrew | optional; not used |
| Python 3 | system/python3 | used only for evidence processing, not by the harness |
| Xcode command-line tools | present | `xcodebuild` possible but not needed |

## 4.2 Harness (prepared, compiled — nothing risky executed)

- `tools/gl_blend_probe.c` — C11, CGL + GL4.1 core offscreen FBO, dual-source
  blend tests with CPU reference, watchdog and signal diagnostics.
- `tools/build.sh` — `xcrun clang` build to `build/tools/gl_blend_probe`
  (nothing outside `build/` is written).
- `tools/README.md` — safety model, modes, expected values, baseline, recovery.

Design points that make it safer than the earlier ad-hoc probes:

1. **Default mode is `--inspect`** (context + `glGetString` only). This was run
   on this machine without a new `*.gpuRestart`.
2. **No default framebuffer drawing without a valid drawable**: `--render`
   attaches a **PBuffer** drawable first and refuses to clear/draw if that fails
   (exit 11). This is precisely the missing piece in the probes that crashed.
3. **Nothing runs silently**: `--render` needs `--yes`; a watchdog
   (`SIGALRM`, default 60 s) aborts a hang; `SIGSEGV`/`SIGBUS`/`SIGABRT` are
   caught and reported with a note pointing at the known crash signature.
4. **No window, no display takeover, no kext/disk/system-file modification**;
   the test is a normal user process and disappears when the test ends.
5. Pixel comparison is against **CPU-computed reference values** (blend equation
   math), not against the driver’s own output, so a silently ignored index-1
   output shows up as a mismatch.

## 4.3 Baseline results (safe modes, executed)

`./build/tools/gl_blend_probe --inspect`:

```
GL_VENDOR   = ATI Technologies Inc.
GL_RENDERER = AMD Radeon RX Renoir Graphics OpenGL Engine
GL_VERSION  = 4.1 ATI-7.0.25
GLSL        = 4.10
GL_ARB_blend_func_extended = present
GL_EXT_blend_func_extended = MISSING
GL_MAX_DRAW_BUFFERS = 8, GL_MAX_DUAL_SOURCE_DRAW_BUFFERS = 1, GL_MAX_COLOR_ATTACHMENTS = 8
extension count = 46
```

`./build/tools/gl_blend_probe --link` (no draw calls):

```
c1 bound to frag data index 1: yes
dual-source shaded linked: SRC1_COLOR ok, SRC1_ALPHA ok
```

No new `*.gpuRestart` or crash report appeared during either run (count stayed at
13 before/after; the resets in §3.8.1 continued to come from
WindowServer/DeepSeek Harness independently). This establishes the **safe
baseline**: the ARB dual-source entry points exist and shaders link; whether the
*rendered result* is correct on iGPU is exactly what `--render` would tell us, and
that test is **not run**.

## 4.4 Test matrix

| Stage | Command | What it exercises | Risk | Approval |
| --- | --- | --- | --- | --- |
| S0 | `gl_blend_probe --inspect` (or `--exts`) | CGL context, GL strings/extensions | minimal (context init) | not required (done) |
| S1 | `gl_blend_probe --link` | shader compile/link, frag-data index binding | low (no submission) | Lead informed (done once) |
| S2 | `gl_blend_probe --render --yes` | PBuffer drawable, FBO clear/draw, 4 pixel tests | **high** (driver crash/GPU reset demonstrated) | **explicit Lead approval required** |
| S3 | loop S2 or add stress | repeatability | higher | separate approval |
| S4 | real Chromium/Electron app with GPU enabled | full ANGLE→OpenGL path | high, user-visible | separate approval |
| S5 | candidate patch + S2/S4 | fix validation | highest | separate approval |

## 4.5 What would count as a reproduction / result

- **Crash/reset**: SIGSEGV in `AMDRadeonX5000GLDriver` (see §3.8.2 stack) or a
  new `*.gpuRestart` during S2 → reproduces the hard failure mode. Collect the
  new crash report/`gpuRestart` and stop.
- **Pixel mismatch** in the dual-source cases (return code 10): a softer,
  deterministic repro. On a driver that ignores the index-1 output the
  `SRC1_ALPHA` case returns ≈`(128,64,191)` instead of `(64,32,223)`; a driver
  that mis-programs the RB+ path could give other values. Record exact pixels.
- **All PASS**: does *not* prove the driver is fine (simple single-draw
  sequence vs ANGLE’s pipeline usage), but it gives a clean baseline for
  before/after comparisons of candidate patches.
- The harness must be accompanied by `stat`/count of
  `/Library/Logs/DiagnosticReports/Kernel_*.gpuRestart` before and after, plus a
  note of which apps were running (WindowServer alone vs an Electron app).

## 4.6 Approval-gated procedure for S2 (render)

Preconditions — all must hold:

1. Lead’s explicit approval in the task thread.
2. Fresh reboot **after** the current unstable boot (see §3.8.1); no GPU resets
   in the last 10 minutes; no Electron/Chromium app running during the test
   (quit DeepSeek Harness/Obsidian/ZCode/etc., or accept that they may be killed).
3. Recovery plan in hand: expected failure = `SIGSEGV`/hang/display corruption;
   recovery = power off/reboot (and after reboot, restore `WindowServer` state,
   do not immediately rerun).
4. Record baseline: `ls -lat /Library/Logs/DiagnosticReports/*.gpuRestart | head`,
   `kmutil showloaded | grep -i -E 'nooted|lilu'`, plus relevant console output.

Run:

```sh
cd /Volumes/WorkSpace/Projects/Hackintosh/NootedRed
./tools/build.sh
# optional: capture the GPU-restart count first
ls /Library/Logs/DiagnosticReports/*.gpuRestart 2>/dev/null | wc -l
./build/tools/gl_blend_probe --render --yes --timeout 30
ls /Library/Logs/DiagnosticReports/*.gpuRestart 2>/dev/null | wc -l
ls -lat ~/Library/Logs/DiagnosticReports | head
```

Stop conditions: any new `*.gpuRestart`, any `SIGSEGV`/`SIGBUS` note from the
harness, display corruption, unresponsive UI, or the watchdog firing. On stop:
reboot; do not run again on the same boot.

Postconditions: save the command output + crash/GPU-reset files; note the exact
mode and whether a drawable was attached; record whether WindowServer restarted
or the display recovered.

## 4.7 Safe paths to test candidate user-space patches later

### 4.7.1 Candidate patches to test (in order of preference)

1. **GL-driver `gfx9_HwInfoInitData` correction** (target of task-1): make the
   driver see Renoir’s real topology instead of Vega “0x8d/4 SE/…”. Root-cause
   fix; needs exact 15.8.1 patch bytes and validation of every field.
2. **GL-driver dual-quad/RB+ branch** analog of the fork’s LegacyBlend: force
   `CB_COLOR_CONTROL.DISABLE_DUAL_QUAD` on the iGPU path (NOP the capability
   branch or clear the caps bit). Near-root fix; loses a blend optimization.
3. **Kernel-side HwInfo steering** (task-2): if the kernel accelerator can supply
   correct data to the user-space driver, no user-space patch may be needed —
   test via a NootedRed test build/EFI.
4. **BFixup-style version lowering** (only as a control/emergency workaround; the
   maintainer does not recommend it).
5. **ANGLE flags** (`use-angle=gl` + `disableBlendFuncExtended`): per-app control,
   useful to prove the trigger path on this machine.

### 4.7.2 Method A (recommended first): process-scoped self-patch in a *test* process

Idea: inject a small dylib into **our own** probe/Electron test process only, and
patch the already-mapped `AMDRadeonX5000GLDriver` image in that process. No disk
writes, no kernel code, no other process affected; the patch disappears with the
process. This mirrors the fork’s “process-private COW pages” principle without a
kext.

Sketch (documentation only — **not implemented, not run**):

```c
// loader.dylib  (only for our own, non-hardened test binary)
// 1. find the mapped image whose path ends with AMDRadeonX5000GLDriver
//    (iterate _dyld_image_count()/_dyld_get_image_header()/_dyld_get_image_name()).
// 2. compute the address of the target function from the Mach-O ("__TEXT,__text"
//    file offset + slide); the on-disk and shared-cache images must be the same
//    build (validate the 16-byte UUID / LC_UUID / first bytes).
// 3. verify the original bytes by SHA-256 of the full function, exactly like the
//    fork's generator does; refuse if unknown.
// 4. mprotect() / mach_vm_protect() the containing page(s) of our own task to
//    RWX, memcpy the replacement bytes, restore RX (or leave RWX only briefly).
// 5. run the probe's inspect/link/render tests and compare against the
//    unpatched baseline on the same boot (run the unpatched copy first).
// 6. print resolved image base, function address, original/patched hashes, and
//    the page protection before/after; fail closed on any mismatch.
```

Why this is the safest *patch validation* route:

- process scope: cannot break WindowServer, the dyld cache on disk, code signing
  metadata or other apps;
- reversible: process exit discards the COW pages;
- testable: same binary can run patched and unpatched, giving a controlled A/B.

Limits/caveats: `DYLD_INSERT_LIBRARIES` is ignored for hardened/platform binaries
— fine for our own ad-hoc-signed probe, **not** for Chrome/Electron (they have
hardened runtime/library validation); a patch that only works in our probe may
still need a kernel page-patch mechanism for real apps. Also the driver may
initialise state before our constructor if the context is created first — patch
before `CGLChoosePixelFormat`/any GL call.

### 4.7.3 Method B: kernel-side page patch (fork approach / NootedRed integration)

Only after Method A shows the exact patch produces correct pixels:

- follow the fork’s design: exact cache UUID + full-function content validation,
  device-ID gate, `vm_protect`/`copyout` only to process-private COW pages,
  restore protection, bounded retries and rollback; **never** touch on-disk
  files; expose a boot-arg gate and IORegistry diagnostics;
- restrict the first on-machine build to a **named test process** (our probe or a
  single Electron app), not WindowServer;
- respect the maintainer PSA (§3.7.3): user-space patching has system-wide
  stability costs; NootedRed should not enable it by default;
- for the **GL** driver the mapping source must be confirmed first: the shared
  cache contains `AMDRadeonX5000GLDriver` path strings (§1), so the same
  cache-page COW technique may apply; if a given process maps the on-disk bundle
  instead, the `_cs_validate_page`/`_cs_validate_range` route (BFixup/Lilu
  `UserPatcher`) is the alternative. Task-3 (`lilu-userpatch`) is investigating
  exactly this; do not duplicate that work here.
- Red flags to check before shipping: AMFI/code-signing revalidation (maintainer
  PSA blames in-memory modification for APFS hash mismatch / update issues),
  page-protection restore failures, and version drift across macOS builds.

### 4.7.4 Method C: BFixup-style (control only)

Useful only as an external control to demonstrate that lowering the reported GL
version changes Chromium’s behavior (if a user can boot with it). Not a fix; not
recommended by the maintainer; the original plugin only supports Big Sur–Sonoma.
Fresh forks (§3.7.2) claim Sequoia; treat as untrusted until they have hardware
reports.

### 4.7.5 Method D: ANGLE flags (app-level control)

The maintainer’s 2024-08-25 statement is the primary evidence for the ANGLE path.
For a **fresh** Chromium/Electron build, the exact switches must be verified
against that build’s command-line docs (e.g. an ANGLE backend selection such as
`--use-angle=gl` plus the ANGLE feature `disableBlendFuncExtended`); do not copy
flag syntax blindly. Because no Chromium is installed here, this can only be
tested with a user-provided build or by installing one, and only with approval.

### 4.7.6 Method E: Metal side (optional, out of scope for this harness)

The fork’s docs warn that a minimal *Metal* dual-source test produced pixel
differences and broke the desktop on their machine; do not run Metal TS/shader
tests on this system without an isolated test environment. The GL harness above
is deliberately CGL-only.

## 4.8 App-level reproduction ladder (only with approval)

1. Control run with GPU acceleration **off** (Electron/Chromium switch
   documented by the app) — establishes that the machine is otherwise stable.
2. Enable GPU acceleration with the app **maximally windowed/minimised**; exercise
   a small, deterministic workload (address bar typing + suggestions, Discord
   server settings, a page with known WebGL); watch for corruption/resets.
3. Collect `*.gpuRestart` + crash reports + `chrome://gpu`/equivalent page.
4. Only after a controlled reproduction: test candidate patches (Method A first
   in the test process; then Method B).

## 4.9 Acceptance criteria for a candidate fix

- Unpatched vs patched A/B on the same boot/build:
  - dual-source S2 cases: unpatched mismatch/crash → patched PASS (and the
    non-dual cases remain PASS);
  - no `AMDRadeonX5000GLDriver` SIGSEGV, no new `*.gpuRestart` during ≥20
    consecutive S2 iterations (if S3 is approved);
  - with the patch, a real Chromium/Electron workload shows no corruption and no
    resets for ≥10 minutes of representative use (after separate approval);
- Patch hygiene: exact macOS build/function-content gate, device-ID gate,
  bounded writes, rollback, diagnostics; no writes to on-disk system files; not
  enabled by default in NootedRed unless the maintainer decides otherwise.

---

## 5. Recommendations / next steps (owners)

1. **Do not run GL render probes on the current boot.** Reboot first; the boot is
   producing GPU resets (WindowServer + Electron) every ~20–60 s.
2. **Offline patch-point work** (no GPU): task-1 should map
   `_gfx9_HwInfoInitData` (0xdf40) and the blend/dual-quad state functions
   (`_glrAMD_GFX9_UpdateHwBlendColorState` 0x9d37,
   `_glrAMD_GFX9_UpdateHwCbDualQuadMode` 0x8134,
   `_glrAMD_GFX9_UpdateHwBlendOptState` 0x7f62, `_glrAMD_GFX9_UpdateHwBlendState`
   0x83e3) against the know-good fields from Mesa/AMD AddrLib, and identify the
   iGPU-vs-dGPU branch in this 7.0.25 binary.
3. **Study the fork’s LegacyBlend logic** (task-3/task-2) as a template: find the
   GL-driver analog of “compute `dualSource || !allowRBPlus` and always program
   `DISABLE_DUAL_QUAD` when the capability is missing”; the fork’s generated
   patch data and `test_legacy_blend_gate.py` clearly document the intended
   behavior change. Porting its *mechanism* (content-validated COW page patch) is
   more valuable than its byte offsets (different macOS build).
4. **Task-3**: confirm whether the GL driver is page-patched via
   `_cs_validate_page` (on-disk bundle) or via a shared-cache COW route in
   practice; expose a `-NRedGLFix` gate and a caller-supplied patch list. Keep it
   off by default until validated.
5. **Reproduction**: after a reboot and with Lead approval, run S2 once
   (`--render --yes`), collect results, and use the same command for A/B with a
   candidate patch (Method A). Report the exact pixel values and reset counts.
6. Consider asking the fork author (or the maintainer) for the hardware
   acceptance data; note the fork is unsolicited third-party code and must be
   reviewed before any of it is merged.

---

## 6. Verified vs. speculation

| Claim | Status | Basis |
| --- | --- | --- |
| #158 is open, 114 comments, last activity 2026-07-13 | verified | GitHub API |
| Maintainer’s 2026-07-13 “potential solution, untested” + `gfx9_HwInfoInitData` screenshot | verified | issue comment + downloaded image |
| No upstream branch/PR/tag/commit fixes #158 | verified | API branches/tags/PRs/commits/code search; master 9ff85a6 |
| 10 issues are closed duplicates of #158 | verified (mapping by exact close timestamps; GraphQL canonical) | API + GraphQL |
| #235 workaround `allowMetalTransferSession NO` | verified (maintainer, multiple confirmations) | issue comments |
| Maintainer PSA: user-space patching destabilises macOS | verified | org discussion #1 |
| BFixup source hooks `_cs_validate_page` / shared cache; original supports ≤Sonoma | verified | downloaded source |
| `steve12311/NootedRed` contains a user-space COW-page patcher + LegacyBlend `74 28`→`90 90`; gated to Darwin 25 | verified | fork clone/source/docs |
| “Cezanne 5800H user confirms Chrome artifacts fixed” | **community claim, not independently verified** | fork docs (zh) |
| `hoaug-tran/BFixup` Sequoia support | **community claim, unverified** | repo README, created 2026-10-16 |
| Local GPU resets + `AMDRadeonX5000GLDriver` SIGSEGV reproduce #158-class failure | verified (crash/reset files) | §3.8 |
| Offscreen `glClear` without drawable crashes; context+strings safe | verified | two crash reports; our inspect/link ran cleanly |
| Runtime: ARB dual-source present, EXT missing, dual-source links | verified | our probe |
| The concrete GL-driver patch bytes for 15.8.1 | **unknown / speculation** | requires task-1/2 reverse engineering |
| Disabling the RB+ dual-quad path fixes GL corruption on Renoir | **hypothesis** (supported by prior report + fork’s Metal result) | prior report §9, fork docs |
| #158 and #235 share a root cause | **maintainer speculation** (“possibly also #235”) | 2026-07-13 comment |
| PBuffer-render S2 is safe on this machine | **unknown** — not run; test needs approval | — |

---

## Appendix A — commands used (evidence reproduction)

```sh
# issue bodies/comments (unauthenticated curl works; gh also authenticated)
curl -sS https://api.github.com/repos/ChefKissInc/NootedRed/issues/158
curl -sS 'https://api.github.com/repos/ChefKissInc/NootedRed/issues/158/comments?per_page=100&page=1'
curl -sS 'https://api.github.com/repos/ChefKissInc/NootedRed/issues/158/comments?per_page=100&page=2'
gh api --paginate 'repos/ChefKissInc/NootedRed/issues/235/comments?per_page=100'
gh api --paginate 'repos/ChefKissInc/NootedRed/issues?state=all&per_page=100'
gh api 'repos/ChefKissInc/NootedRed/issues/158/timeline?per_page=100'
gh api graphql -f query='{ repository(owner:"ChefKissInc", name:"NootedRed") { issue(number:158) { timelineItems(itemTypes:[MARKED_AS_DUPLICATE_EVENT]) { nodes { ... on MarkedAsDuplicateEvent { canonical { ... on Issue { number } } } } } } } }'
gh api 'repos/ChefKissInc/NootedRed/forks?per_page=100&sort=stargazers'
gh api 'repos/ChefKissInc/NootedRed/compare/master...steve12311:master'
git clone --depth 1 https://github.com/steve12311/NootedRed.git   # read-only inspection
curl -sSL -o BFixup-master.zip 'https://github.com/ChefKissInc/NootedRed/files/13575356/BFixup-master.zip'
gh api graphql -f query='{ repository(owner:"ChefKissInc", name:".github") { discussions(first:15) { nodes { number title body } } } }'

# local evidence
ls -lat /Library/Logs/DiagnosticReports/ | head
ls -lat ~/Library/Logs/DiagnosticReports/ | head
B=/System/Library/Extensions/AMDRadeonX5000GLDriver.bundle/Contents/MacOS/AMDRadeonX5000GLDriver
defaults read /System/Library/Extensions/AMDRadeonX5000GLDriver.bundle/Contents/Info.plist
nm -a "$B" | grep -E 'HwInfoInitData|UpdateHwBlend|DualQuad|UpdateHwExportBlockState'
strings -a "$B" | grep -E '^Radeon ' | sort -u
kmutil showloaded | grep -i -E 'nooted|lilu|radeon'
csrutil status
# NOTE: `log show` and `ps` are blocked by the session sandbox here
#       ("log: Cannot run while sandboxed" / "Operation not permitted").

# harness
./tools/build.sh
./build/tools/gl_blend_probe --inspect
./build/tools/gl_blend_probe --link
# ./build/tools/gl_blend_probe --render --yes   # NOT run; requires Lead approval
```

## Appendix B — references

**Upstream**

- Issue #158: <https://github.com/ChefKissInc/NootedRed/issues/158> (last
  maintainer comments 2026-07-13: `#issuecomment-4956347445`,
  `#issuecomment-4956933150`)
- Issue #235: <https://github.com/ChefKissInc/NootedRed/issues/235>
  (workaround: `#issuecomment-4567109847`, 2026-05-28)
- Maintainer PSA: <https://github.com/orgs/ChefKissInc/discussions/1> (2025-03-03)
- Repo (master `9ff85a6`, 2026-10-10): <https://github.com/ChefKissInc/NootedRed>
- Prior in-repo report: `Chromium-OpenGL-Issue-Report.md` (2026-10-15)

**Community**

- Fork with user-space patcher + LegacyBlend:
  <https://github.com/steve12311/NootedRed> —
  <https://github.com/steve12311/NootedRed/blob/master/docs/metal-rendering-fix.md>,
  <https://github.com/steve12311/NootedRed/blob/master/docs/vega-tahoe-r3-test.md>,
  `NootedRed/UserSurfaceSync.cpp`, `NootedRed/UserSurfaceSyncData.hpp`,
  `tools/test_legacy_blend_gate.py`; commits 2026-10-02…2026-10-07.
- BFixup source: attachment links in
  [#issuecomment-1842011907](https://github.com/ChefKissInc/NootedRed/issues/158#issuecomment-1842011907);
  updated forks <https://github.com/hoaug-tran/BFixup> (2026-10-16) and
  <https://github.com/macintelk/BFixup> (2026-10-15).
- Adjacent research (different GPU/stack):
  <https://github.com/icex/macos-raphael-igpu/blob/main/findings/research/transparency-live-composition-20260916.md>

**Local artifacts**

- Harness: `tools/gl_blend_probe.c`, `tools/build.sh`, `tools/README.md`;
  binary at `build/tools/gl_blend_probe` (git-ignored).
- Crash reports: `~/Library/Logs/DiagnosticReports/glblend2-2026-10-18-211253.ips`,
  `glblend4-2026-10-18-211622.ips`.
- GPU resets: `/Library/Logs/DiagnosticReports/Kernel_2026-10-18-21*.gpuRestart`
  (13 files, 21:12:30–21:17:36).
- GL driver bundle: `/System/Library/Extensions/AMDRadeonX5000GLDriver.bundle/`.
- Shared cache: `/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld/`.

---

*Prepared by `repro-evidence` (task-4). No tracked NootedRed source file was
modified; only `analysis/repro-plan.md` and `tools/` were added. No commit was
made and no reboot was performed by this task.*
