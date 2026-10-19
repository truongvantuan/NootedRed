# NootedRed：Chromium 内核程序 OpenGL 加速花屏 / 崩溃问题分析报告

> 调查日期：2026-10-15
> 调查对象：`ChefKissInc/NootedRed`（master，HEAD `9ff85a6`）及其 issue 跟踪系统
> 结论一句话：**问题不在 Chromium，也不在 NootedRed 的内核补丁本身，而在 Apple 的用户态 OpenGL 驱动 `AMDRadeonX5000GLDriver`。NootedRed 让 AMD 锐龙 iGPU 去绑定本来为 Vega 独显准备的这套驱动，而该驱动里大量硬件参数是按独显写死的、没有 iGPU 分支；Chromium 通过 ANGLE 走 OpenGL 提交命令时正好踩到（双源混合 dual-source blend 是最稳定的触发点），驱动判定硬件出错 → 复位 GPU → kill client → 进程 abort。**

---

## 1. 摘要（TL;DR）

| 项目 | 内容 |
| --- | --- |
| 现象 | Chromium/Electron 程序（Chrome、Edge、Discord、VS Code、YouTube Music 等）开启 GPU 加速后花屏、界面错乱，随后黑块、卡死，严重时整个系统 hang 或应用崩溃 |
| 直接触发点 | 双源混合（dual-source blend，`GL_ARB/EXT_blend_func_extended`）；更准确地说，是**混合（blending）相关的整条硬件状态编程路径** |
| 根因 | iGPU 被强制绑定到 `AMDRadeonX5000`（Vega10 独显）驱动栈；其用户态 OpenGL 驱动 `AMDRadeonX5000GLDriver` 里与 iGPU 相关的硬件参数**按独显硬编码**，缺少 iGPU 分支 |
| 崩溃机理 | 命令提交时驱动检测到 GPU 硬件错误 → `gpusGenerateCrashLog` / `gpusKillClientExt` → GPU 复位 → 客户端 `SIGABRT` |
| 为什么 NootedRed 修不了 | 需要打的是**用户态** dylib/bundle 补丁，Lilu 的补丁能力（内核 kext）覆盖不到，且 Lilu 的用户态补丁方式会导致应用崩溃与系统不稳 |
| 现状 | issue #158 自 2023-09 起作为跟踪 issue 长期 OPEN；维护者 2026-07-13 表示"可能找到方案，但尚未测试，也还没法正确实现" |
| 可用规避 | 关闭 Chromium 的 GPU 光栅化 / 硬件加速（官方 FAQ，代价是 CPU 占用与视频卡顿），或改用 Safari / Firefox；第三方 `BFixup.kext` 是降低 GL 版本号的权宜之计，维护者明确不推荐 |

---

## 2. 现象与复现

### 2.1 受影响范围

不是 Chromium 独有，凡是走 AMD 用户态 OpenGL 驱动的程序都可能中招。issue 里出现过的受害者：

- Chromium / Electron 系：Chrome、Edge、Arc、Discord、VS Code、YouTube Music、Cursor
- 其它走 OpenGL 的程序：Sublime Text 4、Firefox（WebGL）、Blender、DOSBox（`output=opengl`）、Godot、英雄联盟客户端，部分情况下的 Minecraft

Safari、以及用 Metal 的应用基本不受影响——因为它们不走那个 GL 驱动。

### 2.2 复现方式（维护者在 #158 给出）

> 1. 打开使用 dual-source blend 的软件，例如 Chrome、Sublime Text 4
> 2. 观察花屏/卡死

### 2.3 崩溃形态

`#158` 里附的 YouTube Music（Electron）崩溃日志是最干净的一份样本：

```
Application Specific Signatures:
Graphics hardware encountered an error and was reset: 0x00000001
Exception Type:  EXC_CRASH (SIGABRT)   "abort() called"

Thread 0 Crashed:: CrGpuMain
3   libGPUSupportMercury.dylib         gpusGenerateCrashLog + 89
5   com.apple.AMDRadeonX5000GLDriver    gpusKillClientExt + 9
6   libGPUSupportMercury.dylib         gpusSubmitDataBuffers + 490
7   com.apple.AMDRadeonX5000GLDriver    glrATI_Hwl_SubmitPacketsWithToken + 122
8   libGLESv2.dylib                    ANGLEResetDisplayPlatform + 2720738   ← ANGLE
```

读法：

1. Chromium 的 GPU 进程（`CrGpuMain`）经 **ANGLE 的 `libGLESv2`** 提交 OpenGL 命令；
2. 命令落到 **`AMDRadeonX5000GLDriver`** 的 `glrATI_Hwl_SubmitPacketsWithToken`（真正的 PM4 命令提交点）；
3. 驱动/内核发现 GPU 硬件错误，走 `gpusSubmitDataBuffers` → `gpusGenerateCrashLog` → `gpusKillClientExt` 把客户端杀掉；
4. 应用收到 `SIGABRT` 崩溃，系统侧对应一次 `gpuRestart`。

也就是说这**不是渲染结果轻微不对，而是直接把 GPU 打到复位**。这与 issue 里"花屏 + 卡死/崩溃"的描述完全一致。

---

## 3. 相关软件栈（为什么会走到一起）

```
┌──────────────────────────────────────────────────────────────┐
│ 应用：Chrome / Electron / Sublime Text / …                    │
│   └─ ANGLE (libGLESv2 / libEGL)  ── 把 GLES 翻译成桌面 GL      │
│        └─ GLEngine (系统 OpenGL 实现，含扩展表/版本号)          │
│             └─ AMDRadeonX5000GLDriver.bundle  ← 用户态厂商驱动 │
│                  └─ libGPUSupportMercury + AMDRadeonX5000.kext │
│                       └─ iGPU 硬件                             │
└──────────────────────────────────────────────────────────────┘
                    ↑
        NootedRed 只能在这里及以下动手（内核 kext）
```

关键点：

- **NootedRed 是内核 kext，通过 Lilu 打补丁。** `NootedRed/Kexts.cpp` 里被 patch 的对象只有：
  `AMDRadeonX6000Framebuffer`、`AMDRadeonX5000HWLibs`、`AMDRadeonX5000`、`AppleBacklight`、`AppleMCCSControl`、`AppleGraphicsDevicePolicy`、`AppleGFXHDA`。
  全部是内核 kext，**没有、也无法 patch 用户态的 `AMDRadeonX5000GLDriver` / `GLEngine`**。
- **NootedRed 靠"伪造 PCI 匹配 + 注入 personality"让 iGPU 绑定独显驱动。** 见 `NootedRed/Personalities/com.apple.kext.AMDRadeonX5000.xml`：
  ```xml
  <key>IOPCIMatch</key><string>0x15DD1002</string>
  <key>IOClass</key><string>AMDRadeonX5000_AMDVega10GraphicsAccelerator</string>
  ```
  `0x15DD` 是 Raven Ridge（Vega 8/11），`Personalities` 里同时还覆盖 `0x15D8 / 0x15E7 / 0x1636 / 0x1638 / 0x164C`（Picasso / Raven2 / Renoir / Lucienne / Cezanne 等），全部被送进 **Vega10 独显加速器**。
  用户态随之匹配的，就是 **`/System/Library/Extensions/AMDRadeonX5000GLDriver.bundle`**——Apple 给 Vega 独显写的那份 GL 驱动。

所以本质是：**用独显的用户态驱动去驱动一颗它不认识的 iGPU。**

---

## 4. 根因分析

### 4.1 直接触发点：双源混合（dual-source blending）

维护者在 #158 中给出的结论（2024-08-25）：

> "We have found what causes the corruption; it's **dual source blend**. Switching ANGLE to OpenGL and ANGLE feature flags to `disableBlendFuncExtended` fixes the corruption. Sublime Text also uses this feature.
> EDIT: Not always. It seems to be **blending functions in general** that are problematic."

即：

- 把 ANGLE 切到 OpenGL 后端、并禁用 `GL_EXT/ARB_blend_func_extended` 这个扩展后，花屏消失；
- 但严格来说不止双源混合，**整个混合相关路径**都不可靠。

机制上说得通：双源混合要求片元着色器输出两组颜色（`gl_SecondaryFragColorEXT`），硬件需要相应地打开颜色缓冲（CB）的双源混合使能位，并正确编程 RB+（Render Backend+）的混合优化状态。这条路径在 iGPU 上被编错了。

### 4.2 深层原因：用户态 GL 驱动里按独显写死的硬件参数

维护者 2026-07-13 的最新判断：

> "The problem is functions like the one pictured below; **no logic to handle the iGPUs, thus using Vega dGPU values** hereby, in theory, causing this and possibly also #235."

以及更早的一条：

> "Also I found that in `AMDRadeonX5000GLDriver`, function `_gfx9_HwInfoInitData` and `_amdUbm_HWL_Init`, that **the device family is hardcoded** instead of being read from the accelerator."

我在本机（macOS 15.6 / darwin 24.6，驱动版本 `7.0.25`）对该 bundle 做了验证，三条证据互相印证：

**(a) 驱动只认识独显，字符串表里没有任何 iGPU 名字。**

```
$ strings AMDRadeonX5000GLDriver | grep -E '^Radeon (Pro )?(RX )?Vega' | sort -u
Radeon Pro Vega 16 / 20 / 48 / 56 / 64 / 64X
Radeon RX Vega 56 / 64
Radeon RX Vega10/12/20 … Prototype
Radeon Vega Frontier Edition
```
没有任何 `Raven / Renoir / Picasso / Vega 8 / Ryzen` 之类的集成显卡条目。

**(b) 维护者点名的两个函数确实存在，且不做家族判断。**

```
$ nm -a AMDRadeonX5000GLDriver | grep -E 'HwInfoInit|amdUbm_HWL_Init'
_gfx9_HwInfoInitData      (0xdf40)
_amdUbm_HWL_Init          (0x5ee3a)
```
反汇编 `_amdUbm_HWL_Init` 可见它直接向结构体写入常量：
```
movl  $0x121011a, (%r12)
movabsq $0x10000000d, %rax ; movq %rax, 0x10(%rbx)
movl  $0x8d, 0x18(%rbx)
```
`_gfx9_HwInfoInitData` 则是从一张源结构里搬字段（SE/RB/CU 数量、对齐参数等），中间没有任何"这是 iGPU"的分支。

**(c) 混合状态路径是一组专用的、按 ASIC 写死的函数。**

```
_glrAMD_GFX9_UpdateHwBlendColorState
_glrAMD_GFX9_UpdateHwBlendOptState
_glrAMD_GFX9_UpdateHwSxBlendOptState
_glrAMD_GFX9_UpdateHwCbDualQuadMode
Gfx9BltDrawRegs::SetupAlphaBlend / GetRbPlusAlphaBlendOpt / GetRbPlusColorBlendOpt
Gfx9BltResFmt::GetBlendClamp / GetBlendBypass
```

反汇编 `_glrAMD_GFX9_UpdateHwBlendColorState`（`0x9d37`）可见它自己拼 PM4 寄存器写包：

```
9d37: … 从 0x3bc0(%rax) 起读 4 个 float（混合常量 RGBA）
9dd0: movabsq $0x105c0046900, %rcx      ; PKT3 SET_CONTEXT_REG，count=4
9dd2: movq    %rcx, (%rax)              ; 头部 + 寄存器索引 0x105
9dd5: vmovups %xmm0, 0x8(%rax)          ; 4 个 dword 数据
9dda: addq    $0x18, %rax               ; 前进 6 dword
```

`0xC00<count>6900` 中 `0x69` 正是上游 amdgpu 定义的 `PACKET3_SET_CONTEXT_REG`（`drivers/gpu/drm/amd/amdgpu/soc15d.h:431`），紧随其后的 dword 是**寄存器索引**。把各函数里内联的常量与上游 gfx9 寄存器定义（`gc_9_0_offset.h`）对照，命中的寄存器名与函数名一一对应：

| 函数 | 写出的寄存器索引 | 上游定义 |
| --- | --- | --- |
| `UpdateHwBlendColorState` | `0x105`（连写 4 个） | `mmCB_BLEND_RED/GREEN/BLUE/ALPHA` |
| `UpdateHwBlendOptState` | `0x1d7` | `mmSX_BLEND_OPT_CONTROL` |
| `UpdateHwCbDualQuadMode` | `0x202` | `mmCB_COLOR_CONTROL` |
| `UpdateHwShadeModelState` | `0x1b5` / `0x205` | `mmSPI_INTERP_CONTROL_0` / `mmPA_SU_SC_MODE_CNTL` |

也就是说：**混合/插值/CB 控制这些寄存器的编程，全部由 `_glrAMD_GFX9_*` 这组"gfx9 通用（实为 Vega 独显）"函数负责，里面写死了独显的取值**。iGPU 命中同一组函数，于是 CL 层面的寄存器值就用错了。

结论：**根因是"iGPU 走了独显的用户态 GL 驱动，而该驱动在混合相关路径上只按独显建模"。** `dual-source blend` 只是最容易稳定触发它的用例。

### 4.3 为什么表现为"花屏然后崩溃"

1. 寄存器编程错误 → 光栅化结果错乱 → 屏幕花屏/错块；
2. 命令流继续推进，驱动或内核发现状态不一致 / 硬件报错；
3. `gpusSubmitDataBuffers` → `gpusGenerateCrashLog`（`Graphics hardware encountered an error and was reset`）→ `gpusKillClientExt`；
4. 杀掉 GL 客户端 → 应用 `SIGABRT`。

---

## 5. 证据汇总

### 5.1 issue 跟踪

| issue | 状态 | 内容 |
| --- | --- | --- |
| **#158** 「Blend shader functions cause corruption, freezes or crashes」 | **OPEN** | 本问题的**主跟踪 issue**。2023-09 开，114+ 条讨论，维护者在此给出 dual-source blend 结论与 2026-07 的新假设 |
| #13 「Some content and heavy applications cause GPU panics (hangs) or artefacts」 | CLOSED | 与 #235 同源（GPU page fault） |
| #122 「Freezing and Screen Tearing with Hardware Acceleration in Edge」 | CLOSED | 作为 #13 的重复关闭，早于 #158 |
| #187 「Usage of any Browser other than Safari causes hang or hardlock」 | CLOSED | 同一问题的浏览器侧表现 |
| #165 / #192 / #200 / #247 / #268 / #307 / #355 / #384 / #391 / #446 | CLOSED | 各种"应用花屏/崩溃"的重复报告（Discord、VS Code、Sublime、alacritty、Zen 浏览器…） |
| #235 「[Sonoma+] Specific compute tasks may hang」 | OPEN | 维护者认为"理论上同源"；其 workaround 是关掉 VideoToolbox 的 `allowMetalTransferSession`，与本问题不是同一件事 |

### 5.2 维护者原话（按时间）

- 2023-09：issue 建立，"软件如 Chrome、Sublime Text 4 会导致损坏与卡死"。
- 2024-06-27：*"There is no fix available, neither is a fix easy due to the design of Lilu. I am planning to make a Lilu replacement before I try to actually fix it."*
- 2024-08-25：*"it's dual source blend … not always, blending functions in general."*
- 2025-03-02：*"To resolve this issue **user-space patches are needed**, more complex ones than you can do with Lilu … Lilu user-space patching causes issues anyways, like app crashes and system instability."*
- 2026-07-13：*"I have potentially found a solution. Don't get too excited: I haven't tested it yet, and still can't implement it properly as stated previously."* ＋ *"no logic to handle the iGPUs, thus using Vega dGPU values."*

### 5.3 崩溃日志

`#158` 附件 `YouTube_Music_Helper_GPU_2023-10-28-113038.crash.txt`（macOS 11.7.7，Electron）——见 §2.3 的栈，`Graphics hardware encountered an error and was reset: 0x00000001`。

### 5.4 本地二进制验证

见 §4.2 的 `nm` / `strings` / `objdump` 输出（本机 `AMDRadeonX5000GLDriver` 版本 `7.0.25`；崩溃日志里那台是 `4.6.21`，跨版本行为一致）。

---

## 6. 为什么 NootedRed 目前修不了

1. **补丁层级不对。** 出错代码在用户态 `AMDRadeonX5000GLDriver.bundle`。Lilu/NootedRed 的打补丁能力在内核 kext 层面（`KernelPatcher`），够不到用户态 bundle。
2. **Lilu 的用户态补丁方式本身有副作用。** 维护者原话：causes app crashes and system instability。第三方 `BFixup.kext` 就是典型——它去 patch `GLEngine`，用降低上报的 GL 版本来规避，结果是"不推荐的 hack"，在部分系统上还会把硬件加速整个关掉。
3. **需要一个新的用户态补丁框架。** 维护者明确说要先做一个 Lilu 的替代品，才谈得上真正修复。
4. **VTable wrap hack 本身有 bug。** 维护者在 #158 里指出：现有那套 wrap（配合 `AMDHWAlignManager` 做计算）在"被 wrap 的函数内部再调用 this 的另一个虚函数"时会调错函数——这会进一步污染 iSurface/对齐相关路径。

---

## 7. 规避方案与代价

按"推荐 → 不推荐"排列：

**① 关闭 Chromium 的 GPU 光栅化 / 硬件加速（官方 FAQ 方案）**

- 在 `chrome://flags` 里禁用 GPU Rasterization，或整体关掉硬件加速；
- 打不开浏览器时：`open -a "Google Chrome" --args --disable-gpu`；
- 代价：网页滚动/视频转由 CPU 处理，CPU 占用升高、笔记本更热、YouTube 视频可能卡顿。这是"能用但不爽"的折中。

**② 换浏览器**

- 用 Safari（走 Metal，不受影响）；Firefox 需要关掉 `layers.acceleration.disabled` / `webgl.disabled` 才稳，同样失去加速。

**③ 只针对触发点关扩展（维护者验证过的组合）**

- ANGLE 切到 OpenGL 后端 + 禁用 `disableBlendFuncExtended` 特性；
- 注意：这是维护者在排查中验证的**诊断组合**，不是官方开关；在多数 Chromium 版本上不易配置到，且只解决"混合"这一类触发，不代表整条 GL 路径都好了。

**④ 第三方 `BFixup.kext`（不推荐）**

- 原理：patch `GLEngine`，让上报的 OpenGL 版本降级（4.1 → 3.2/3.3），应用因此不去申请那些坏掉的扩展；
- 维护者在 issue 里两次加注："This is not a proper fix … I do not recommend using it."；部分系统上会导致应用硬件加速整体失效；
- 使用它还会违反 issue 模板里"不使用 BFixup 等冲突软件"的条款。

**⑤ 调 VRAM**：有用户报告默认 512MB 时不出花屏但失去加速、加到 2GB 后花屏——属于改症状不改病根，仅作参考。

---

## 8. 可能的修复方向

1. **正确建模 iGPU 的硬件参数。** 目标是让 `_gfx9_HwInfoInitData` / `_amdUbm_HWL_Init` / 芯片家族判定读到 iGPU 的真实值，而不是 Vega 独显值。维护者 2026-07 的"potentially found a solution"指向的就是这类函数，但受限于"没有可用的用户态补丁框架"而无法落地。
2. **实现用户态补丁能力。** 维护者已把"做一个 Lilu 替代品"列为前置工作；只有这一步到位，才能在 `AMDRadeonX5000GLDriver` / `GLEngine` 里做语义正确的补丁（而不是 BFixup 式的版本号降级）。
3. **修正 `AMDHWAlignManager` 的 VTable wrap**，避免"wrap 内再调虚函数调错"污染对齐/iSurface 路径。
4. **让 iGPU 尽量走非 GL 路径。** Chromium 在 macOS 上可以走 Metal（ANGLE 的 Metal 后端，对应 `AMDRadeonX5000MTLDriver`），Meta 路径本身与 GL 驱动的问题解耦；但 Metal 后端在 iGPU 上也有自己的问题，不能简单当万能药。
5. **短期内的工程折中**：在 NootedRed 侧识别"这是 iGPU"并主动抑制有问题的扩展上报——但扩展上报在用户态 `GLEngine` 里，回到同样的问题 2。

---

## 9. 根因修复的可行性（追加分析）

### 9.1 缺陷性质：是"值和分支错了"，不是"算法缺了"

对 `AMDRadeonX5000GLDriver`（本机 7.0.25）补充静态分析，三条可复现的事实：

**① 渲染层 100% 只有 gfx9。**

```
$ nm -a AMDRadeonX5000GLDriver | grep -oE '_glrAMD_GFX[0-9]+' | sort | uniq -c
    494 _glrAMD_GFX9
```

`_glrAMD_GFX10_*` 一个都没有。也就是说驱动内部**不存在第二条"正确"的 ASIC 路径**可供切换——iGPU 一定走这套按 Vega 写的代码。

**② `_gfx9_HwInfoInitData` 把"我是谁"直接写死成 Vega10。**

```
    df40: movl  %edx, %eax            ; arg3，家族/变体位
    ...
    e068: testl $0x70000, %eax        ; 取 arg3 的 bits[18:16]
    e06d: je    0xe0b5
    e075: cmpl  $0x13, %r8d           ; 按源结构里的一个计数值分档
    e079: ja    0xe0c0
    e07b: movl  $0x8d, (%rdi)         ; ← 写死 family = 0x8D
    ...
    e0c0: cmpl  $0x27, %r8d
    e0c6: movl  $0x8d, (%rdi)         ; ← 同上
    e0fd: cmpl  $0x31, %r8d
    e103: movl  $0x8d, (%rdi)         ; ← 同上
    e14e: movl  $0x0, (%rdi)          ; 超出范围 → 直接写 0
```

`0x8D` 即上游 amdgpu 的 `AMDGPU_FAMILY_AI = 141 = 0x8D`（Vega10，见 `include/uapi/drm/amdgpu_drm.h:1665`）；`AMDGPU_FAMILY_RV = 142 = 0x8E`（Raven，iGPU）在这个函数里**一次都没出现**。这证实了维护者说的 "the device family is hardcoded"：函数按计数值 19 / 39 / 49 分三档，但三档全部回落到 Vega10，超出范围就写 0。

（旁证：addrlib 侧的 `Addr2::Gfx9Lib::HwlConvertChipFamily` 也只对 `0x8D` 做特判，其余输入一律返回同一个值——同一套"只认 Vega10"的写法。）

**③ 一个 caps 字节是"这颗芯片是谁"的总开关。**

驱动内部结构 `ctx+0x12e0` 指向一个小结构，其 `byte[2]` 同时决定两件事：

```
_glrAMD_Hwl_CreatePipeInfo:
    movzbl 0x2(%rax), %eax
    movzwl pipeInfoSizes(,%rax,2), %esi     ; 用它索引 6 种 pipe info 变体之一

_glrAMD_GFX9_UpdateHwSxBlendOptState:
    testb  $0x8, 0x2(%rax)
    je     0x8279                           ; 该位为 0 → RB+ 混合优化状态全部清 0
_glrAMD_GFX9_UpdateHwBlendOptState:
    testb  $0x8, 0x2(%rcx)
    je     0x7fd0                           ; 该位为 0 → 根本不写 SX_BLEND_OPT_CONTROL(0x1d7)
```

即：**RB+（Render Backend+）混合优化要不要编程、按哪套 pipe 参数编程，全由这一个 byte 决定。** 如果它在 iGPU 上取到了独显的值，驱动就会去编程 `SX_BLEND_OPT_CONTROL` 的优化位——这与"只有混合路径出问题、dual-source 最稳定触发"的现象高度吻合。

### 9.2 结论：原理上可行，工程上三重障碍

**原理上可行**：同一颗 iGPU 在 Linux 上跑 OpenGL 是正确的（radeonsi），说明硬件本身没问题、正确参数客观存在。所以这不是"做不到"，而是"没人做过"。

| 障碍 | 说明 |
| --- | --- |
| 层级 | 要改的是用户态 bundle，NootedRed/Lilu 够不到；维护者明确说要先做 Lilu 替代品 |
| 正确值未知 | Apple 从未出过 AMD APU 的 Mac，没有参考实现；只能从 Linux amdgpu / 逆向推导 |
| 不止一处 | 维护者说 "multiple issues at once"，且还要"去掉从 Navi 驱动偷来的那部分"（内核侧 `AMDRadeonX6000Framebuffer`）；混合路径大面积受影响，说明错误散布在 caps / 格式 / 混合等多个函数里 |

### 9.3 分层方案

| 层次 | 做法 | 是否根治 | 当下可行性 |
| --- | --- | --- | --- |
| **A** | 用户态补丁框架 + 让 `_gfx9_HwInfoInitData` 等按真实家族取值 | **是** | 前置条件不存在，工作量大 |
| **B** | 精准关掉出错的那条硬件路径：清掉 `caps[2] & 0x8`，使 RB+ 混合优化不再被编程 | 接近根治（只损失混合优化性能，保留 GL 版本与扩展） | 需 dyld 级补丁；BFixup 证明这条路走得通，只是切入点和粒度都不对 |
| **C** | 让 ANGLE 不走到该路径（OpenGL 后端 + `disableBlendFuncExtended`）或走 Metal | 否（逐应用） | 可用，但非根治 |
| **D** | 关 Chromium GPU 光栅化 / 硬件加速 | 否 | 官方现状 |

> **重要限定**：9.1 的三条是**静态分析结论，已复现**；9.3 层次 B 的"这样就能修好"是**由这些结论推出的假设，未在真机验证**。维护者 2026-07 的"可能方案"同样只停留在 "in theory / haven't tested"。层次 B 是目前最省事、最值得优先验证的路径——它只需改用户态驱动里的一个 capability 位。

---

## 10. 参考

- 主跟踪 issue：<https://github.com/ChefKissInc/NootedRed/issues/158>
- 相关重复/衍生：`#13`、`#122`、`#165`、`#187`、`#192`、`#200`、`#235`、`#247`、`#268`、`#307`、`#355`、`#384`、`#391`、`#446`
- Oracle 崩溃日志附件：`#158` comment（2023-10-28，YouTube Music / Electron）
- 官方 FAQ（workarounds）：<https://chefkiss.dev/applehax/nootedred>
- 上游寄存器定义：`torvalds/linux` → `drivers/gpu/drm/amd/include/asic_reg/gc/gc_9_0_offset.h`、`drivers/gpu/drm/amd/amdgpu/soc15d.h`
- 本仓库相关代码：`NootedRed/Kexts.cpp`、`NootedRed/Personalities/com.apple.kext.AMDRadeonX5000.xml`、`NootedRed/DriverInjector.cpp`

---

## 附录 A：复现命令（本地取证用）

```sh
# 1) 确认 iGPU 被塞进了 Vega10 加速器
grep -n "IOPCIMatch" -A2 NootedRed/Personalities/com.apple.kext.AMDRadeonX5000.xml

# 2) 确认 GL 驱动只认独显
B=/System/Library/Extensions/AMDRadeonX5000GLDriver.bundle/Contents/MacOS/AMDRadeonX5000GLDriver
strings -a "$B" | grep -E '^Radeon (Pro )?(RX )?Vega' | sort -u

# 3) 确认混合状态函数按 gfx9 写死
nm -a "$B" | grep -E 'UpdateHwBlend|UpdateHwCbDualQuad|HwInfoInitData|amdUbm_HWL_Init'
objdump -d --start-address=0x9d37 --stop-address=0x9e00 "$B"   # UpdateHwBlendColorState
```

## 附录 B：本文档中"已验证"与"引用"的边界

- **本地二进制验证（可复现）**：§4.2 (a)(b)(c)、§5.4 的符号、字符串、反汇编与寄存器索引对照表；§9.1 的三条（渲染层只有 gfx9、`_gfx9_HwInfoInitData` 写死 `0x8D`=Vega10、caps 字节同时决定 pipe info 与 RB+ 混合优化）。
- **引用维护者结论（未独立复现）**：dual-source blend 是触发点、ANGLE 切换 + `disableBlendFuncExtended` 可规避、2026-07 的"可能方案"。**注**：维护者所称"device family is hardcoded"已由 §9.1 ② 独立证实。
- **纯假设（未验证）**：§9.3 层次 B——清掉 RB+ 混合优化 capability 位即可修复 dual-source 花屏。
- **来自用户报告**：各类具体应用的崩溃表现、VRAM 相关性。
