# VDA VA 数据 — Tahoe 26.7.1 (25G241) 证据

生成命令：

```
python3 tools/gen_vda_va_data.py --root /Volumes/Tahoe --output NootedRed/VDAVADataTahoe.hpp
```

输出文件 `NootedRed/VDAVADataTahoe.hpp`（namespace `VDAVADataTahoe`），`--check` 通过。

## 来源

- dyld shared cache（AppleDrivers）：`/Volumes/Tahoe/System/Library/dyld/dyld_shared_cache_x86_64`
- cache UUID：见生成器 PROFILES["26.7.1"]（来自 `/Volumes/Tahoe/System/Library/CoreServices/SystemVersion.plist` 对应缓存头）
- 驱动版本：`AppleVideoDecoder` / `AppleVideoEncoder` 均为 **7.1.8**（与 15.8.1 相同）

## 关键发现

1. **补丁语义与 15.8.1 完全一致**：站点字节模式逐字节相同，所有相对偏移（符号 → 站点）不变。7.1.8 在两个系统版本间二进制层面相关函数未变。
2. **跨页拆分**：`ForceGfx9VideoProcessors` 的站点在 Tahoe 缓存中横跨两页边界（15.8.1 中单页容得下）。生成器 `build_plan` 将单条 spec 按页拆为多条记录，最终：
   - 页数：7
   - 记录数：10
   - 站点数：12
3. **字节验证**：生成时逐站点对比缓存读取字节与 spec `find` 模式；`--check` 独立复核。曾对一次首跑读得 NOP 填充的异常做双重独立诊断（host 卷与 `/Volumes/Tahoe` 卷同地址均读得 `41 81 fc 8d 00 00 00`），确认为一次性读异常，结果可信。

## 版本门接线

`NootedRed/NRed.cpp` 中 `getKernelVersion() >= KernelVersion::Tahoe` 分支（置于 `>= Sequoia` 之前）选择 `VDAVADataTahoe`；页数上限 `kMaxNativePages = 16`（VA 7 + GVA 1）足够。

## 事故记录：Page0 污染导致运行期 identify 补丁失效（2026-10-20 修复）

**症状**：`-NRedVDA` 下 HEVC/AVC 硬件编解码全部回退软件；`VTEncoderXPCService`/
`VTDecoderXPCService` 日志出现 `GVA error: AVD_api.Create failed err=5`（找到物理加速器
idx 0 但创建失败）。

**根因**：首版 `VDAVADataTahoe.hpp` 的 Page0 页镜像在 0xda9–0xde8 区间有 62 字节与真实
stock 不符（混入的是更早一版实验性 identify 补丁写入后的字节）。生成时机器正处于
`-NRedVDA` 启动状态：Lilu 的 `cs_validate_page` 钩子把补丁字节写进了 dyld 缓存的
**文件页缓存**，生成器经页缓存读到的"stock"实际是上一版 kext 的已补丁页。整页比对在
之后任何干净启动上都会失败 → Page0 上的关键补丁 `IdentifyForceFamily5`（把 0x1638
分类为 VA family 5）从未生效 → VA 驱动无法识别 GPU → AVD_api.Create 失败。

**修复**：用干净页（经 file==内存双向核对）重建 Page0 并重算 `TextSHA256`；
`--check` 通过。其余 6 页经逐字节核对仅含合法补丁点差异。

**参考哈希来源与 stock 性论证**（响应外部评审追问）：重建 Page0 的字节取自受影响
启动的**活内存页**（经 dyld slide 换算后与文件读数逐字节比对，零差异）。该来源
可证明未被污染：污染只能由 kext 的 `cs_validate_page` 钩子写入，而旧 kext 携带的
就是被污染的 Page0 镜像——它对真实 Page0 的整页比对必然失败，因此旧 kext **从未
写入过该页**（活内存核验证实：13 个站点中唯独 Page0 的 identify 站点为 ORIGINAL，
其余 12 个为 PATCHED）。`TextSHA256`（`6e0be98a…`）是生成器对重建后整段 `__text`
的计算值；把 12 个站点恢复为各自 `find` 字节后重算哈希不变，证明站点区域是唯一的
差异来源、站点之外（含曾被污染的 0xda9–0xde8）与缓存读数一致。最终门禁仍是部署
重启后的活内存核验（patchcheck 全 12 站点 PATCHED）+ VT 硬件编解码探针。

**防复发**：`gen_vda_va_data.py` / `gen_vda_gva_data.py` 新增
`warn_if_live_patched_cache()`——检测到在 `-NRedVDA`/`-NRedAVC` 启动的活系统上读缓存时，
`--check` 输出醒目警告，而**生成（非 `--check`）直接拒绝执行**（exit 1），仅在显式
传入 `--force-live-cache` 时放行；`committed_stock_page(s)` 函数头加注 DANGER 说明。
kext 侧 `patchNativePage()` 新增一次性诊断：某声明页的所有站点字节都匹配但整页镜像
不匹配时输出 SYSLOG（`stale table?`），杜绝静默跳过。

**教训**：凡经 `read()` 读取活系统 dyld 缓存路径（`/System/Volumes/Preboot/Cryptexes/...`、
`/System/Cryptexes/...`）都会经过可能被补丁污染的页缓存，且同一地址的字节会随页缓存
驱逐/再验证在 stock 与 patched 之间翻转。CFG 分析、数据生成、`--check` 均受影响；关键
结论必须用干净启动或离线卷复核。
