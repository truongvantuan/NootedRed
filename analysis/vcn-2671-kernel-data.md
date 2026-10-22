# VCN 内核数据 — Tahoe 26.7.1 (25G241) 证据

生成命令：

```
python3 tools/gen_vcn_kernel_data.py \
  --kc /Volumes/Tahoe/System/Library/KernelCollections/SystemKernelExtensions.kc \
  --root /Volumes/Tahoe --darwin 25.6.0 \
  --output NootedRed/VCNKernelDataTahoe.hpp
```

输出文件 `NootedRed/VCNKernelDataTahoe.hpp`（namespace `VCNKernelDataTahoe`，`--check` 通过）。

## 来源

- KernelCollection：`/Volumes/Tahoe/System/Library/KernelCollections/SystemKernelExtensions.kc`
- KC UUID：`07377859-55FE-9F0A-2469-D6714FE1AC25`
- Darwin：25.6.0
- 驱动版本：X5000 / X6000 均 **7.1.8**（与 15.8.1 相同）

## 与 15.8.1 的关键差异

**Guard getter 函数字节数不同，不可跨版本共用**：

- 15.8.1：`Getter5000_1` / `Getter6000_1` 为 12 字节
- Tahoe 26.7.1：同一 getter 多出 `24 01`（`and $1, %al`），为 **14 字节**

因此 guard 表按版本分离，运行期由 `VCNBridge.cpp` 的 `useTahoeVCNData()` 选择对应 guards/table 符号。

## 接线要点

- 头文件以 `using` 别名复用 `VCNKernelData.hpp` 的 struct 类型（运行期免模板选择）。
- 新增 `getCallPatches(count)` helper；X6000 调用点块运行期选 `getCallPatches` / `SignalSymbol`，`addresses[32]` 数组 + 计数上限守卫，替代 `arrsize(CallPatches_Sequoia)`。
- `isSupportedOS()` 增加 Darwin 25.6；`isSupportedBuild()` 增加 `25G` 前缀分支。
