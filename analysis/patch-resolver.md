# User-space patch resolver 原型

日期：2026-10-19  
分支：`research/patch-resolver`  
基线：`feature/multi-os-multi-apu`

## 目标

降低“每个 macOS 版本写一整页 4 KiB 页镜像”的维护量：先用带 mask 的短上下文定位补丁点，
只有页镜像匹配时才走最高安全路径；resolver 仅作为未匹配版本的 opt-in fallback。

## 数据模型

```cpp
struct SignaturePatch {
    const UInt8* context;      // window around the patch site
    const UInt8* mask;         // 0xFF = must match, 0x00 = wildcard
    size_t       contextSize;
    size_t       patchOffset;  // relative to context start
    const UInt8* replace;
    size_t       replaceSize;
    size_t       skip;
    size_t       count;
    UInt64       pageOffset;   // ~0 = any page
};
```

当前 15.8.1 原型生成四个 32 字节上下文：

| 目标 | 页偏移 | 补丁点 |
| --- | --- | --- |
| GL HwInfo | `0xE000` | `+0x81` |
| GL dual-quad | `0x8000` | `+0x160` |
| MTL gate | 任意 | `+0x164` |
| MTL setz | 任意 | `+0x198` |

mask 目前全 `0xFF`；后续可以对版本间稳定/不稳定字节设置 wildcard。

## 运行时

- 默认关闭；必须同时有 `-NRedGLFix` 和 `-NRedGLFixResolve`。
- `patchNativePage` 先尝试完整页镜像；
- 只有页镜像不匹配时才调用 `patchSignaturePage`；
- 每个签名在同一页内按 `skip/count` 定位，命中后临时关闭内核写保护写入；
- 未命中不报错，只是 no-op。

## 安全边界

- resolver 只对通过代码签名校验的页执行；
- 上下文 32 字节、可加 mask；当前全字节匹配，误命中概率低；
- 但 MTL 签名没有 pageOffset/module 过滤，仍建议：
  - 增加 vnode/模块识别；
  - 增加更长上下文/函数哈希；
  - 每个新 macOS 版本单独验证命中点和结果；
- resolver 不能替代“在目标版本上验证语义”；它只减少数据量，不保证版本无关。

## 实机日志发现的问题与修复

在 15.8.1 上用 resolver 构建启动后，`dmesg` 显示大量：

```text
Resolver: failed to find 1 site(s) for signature 2
Resolver: failed to find 1 site(s) for signature 3
```

原因不是签名本身错误，而是**页缓存被第一次 patch 修改后**，后续校验拿到的已经是替换后的页：

- 第一次校验：完整页镜像匹配，正常 patch；
- 之后同一页再次被校验：页内容已经不含原始签名上下文；
- resolver 仍尝试扫描，失败并刷日志。

修复：

- 新增 `isPatchedPage()`：在页镜像不匹配后，先检查该页是否只是“我们 patch 过的版本”；
- 如果是，直接返回，不再进入 resolver；
- resolver 的失败日志改为 `DBGLOG`，默认 boot-args 下不再刷屏。

这解释了为什么之前日志只有 resolver 失败、没有 `Resolver patched`：resolver 被调用的时机大多是在已 patch 的页上。

## QA 模式

为了证明 resolver 本身会 patch，而不是只被页镜像路径绕过：

```text
-NRedGLFix -NRedGLFixResolveOnly
```

`-NRedGLFixResolveOnly` 会跳过完整页镜像，直接走签名 resolver。它只用于测试：

- 成功时日志会显示 `Resolver patched a signature site ...`；
- 失败时是静默的（DBGLOG）；
- 不要在日常使用中启用。

## 当前状态

- 代码已实现 `SignaturePatch`、`-NRedGLFixResolve`、`patchSignaturePage`；
- 15.8.1 四个签名由当前页镜像生成并校验上下文匹配；
- release 构建通过；
- **QA 模式已实机验证（2026-10-19 00:33）**：
  - 加载的 kext UUID 与本地 resolver 构建一致；
  - boot-args：`-NRedGLFix -NRedGLFixResolveOnly`；
  - Metal pipeline：
    `dual=0 control=00cc0010 disable=0`，`dual=1 control=00cc0011 disable=1`；
  - Metal 真实渲染 + blit + CPU 对比：PASS/PASS；
  - 无新的 `gpuRestart`；
  - 说明 resolver 签名匹配、patch 写入和条件化结果都实际生效。

注意：`-NRedGLFixResolveOnly` 只是测试模式，日常使用应移除它，保留正常
`-NRedGLFix`（页镜像优先）。

## 后续

1. 在 15.8.1 上用 `-NRedGLFixResolve` 重启，确认 resolver 日志和 GL/Metal 行为；
2. 对另一个 macOS 版本提取签名，统计命中率；
3. 增加模块/pageOffset 过滤和更长上下文；
4. 命中率稳定后再考虑把 resolver 作为多版本的主要数据形式。
