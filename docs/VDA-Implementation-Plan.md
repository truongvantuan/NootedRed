# VDA / Hardware Video Decode — Implementation Plan

This branch is the dedicated VDA/VCN workstream. It builds on the `DeviceProfile`/`MediaPolicy`
layer from `feature/device-profile`.

## Current state

- Phase 1 (media capability skeleton) is implemented. `DeviceProfile::MediaPolicy` now carries:
  - `vcnGeneration` (`0x0100` VCN 1.0, `0x0202` VCN 2.2);
  - `vcnFirmware` (`ativvaxy_rv.dat` / `ativvaxy_nv.dat`);
  - `vcnRingSize` / `vcnFenceSize`;
  - `decode.h264` / `decode.hevc` / `decode.av1` capability flags.
- Every profile still has:
  - `hasUVD0 = false`
  - `hasVCE = false`
  - `hasVCN0 = false`
- `NootedRed/VDA.{hpp,cpp}` parses the opt-in `-NRedVDA` boot argument (default off), logs the profile
  media policy, and exposes `VDA::mediaEnginesEnabled()` as the runtime gate. In Phase 1 it is always
  `false` because no bring-up has run; requesting the boot argument only produces diagnostic messages
  (plus iGPU properties).
- `X5000::wrapSetupAndInitializeHWCapabilities()` still reads the engine flags from the profile and now
  also requires the VDA gate, so the profile remains the only capability source and `-NRedVDA` is the only
  runtime opt-in.
- Renders/Chromium fix is independent: `-NRedGLFix` remains a graphics-only policy.
- No VDA/VCN hardware decode is enabled yet.
- Builds pass in release, debug and releasedbg. Runtime/reboot validation of Phase 1 is pending.

## Target data path

Typical modern macOS path:

```text
Chromium / AVFoundation
  -> VideoToolbox
  -> VDA / VTDecoderXPCService
  -> AppleVADriver / AMDRadeonX5000VCE (kernel)
  -> VCN engine + firmware
```

Renoir is a VCN 2.x-class APU; Raven/Picasso are VCN 1.0-class. The exact generation belongs in
`MediaPolicy`, not in hardcoded paths.

## Phases

### Phase 1 — media capability skeleton — implemented

- Extended `MediaPolicy` with:
  - `vcnGeneration` — major << 8 | minor, also the firmware loader `ipVersion`
    (`kVcn1_0 = 0x0100`, `kVcn2_2 = 0x0202`);
  - `vcnFirmware` — `ativvaxy_rv.dat` (VCN 1.0) or `ativvaxy_nv.dat` (VCN 2.2), matching the blobs
    embedded by `HWLibs.cpp`;
  - `vcnRingSize` / `vcnFenceSize` — future VCN ring/fence allocation sizes in bytes;
  - `decode.h264` / `decode.hevc` / `decode.av1` — hardware capability flags (AV1 is false: VCN 1.x/2.x
    have no AV1 decoder).
- All profiles keep `hasUVD0`/`hasVCE`/`hasVCN0` false. Compile-time assertions in
  `DeviceProfile.cpp` reject a profile with an enabled engine or missing VCN data.
- Added the `-NRedVDA` boot argument (default off, independent of `-NRedGLFix`). It is parsed in
  `VDA::init()`, and Phase 1 only uses it for diagnostics in `VDA::processPatcher()`; no MMIO, firmware or
  engine access happens. The default path only logs under `-NRedDebug`.
- `X5000` now gates the profile engine flags with `VDA::mediaEnginesEnabled()` (opt-in requested *and*
  bring-up ready), which is `false` in Phase 1.
- Verification: `xmake` passes for release, debug and releasedbg; media flags cannot change at compile
  time, so the graphics path is untouched. One boot on a target machine is still required to confirm no
  runtime regression (`-NRedVDA` absent and present).

### Phase 2 — firmware / PSP bring-up

- Confirm VCN firmware names per family (the tree already references `ativvaxy_rv.dat` for VCN 1.0 and
  `ativvaxy_nv.dat` for VCN 2.2 in HWLibs; the HWLibs comment says VCN 2.1, but it passes `0x0202` as
  the firmware `ipVersion`, and the Linux AMD hardware list classifies Renoir/Cezanne as VCN 2.2).
- Ensure PSP/RLC firmware loading, VCN0 firmware, and power-gating setup.
- Read back engine status; no user-visible decode yet.
- Keep media disabled if firmware load fails.

### Phase 3 — VCN rings / engine

- Allocate VCN rings and doorbells.
- Enable `hasVCN0` only for the tested profile.
- Verify command submission / ring progress.
- Add diagnostics to the media log tag.

### Phase 4 — VideoToolbox/VDA exposure

- Ensure `VTDecoderXPCService` can open a hardware decoder.
- Validate H.264/HEVC decode surfaces and format compatibility.
- Check Chromium hardware decode path.

### Phase 5 — multi-APU / multi-macOS

- Add MediaPolicy values per APU profile.
- Add OS/version-specific media data where required.
- Keep DeviceProfile as the only device selector.

## Required data collection

Use `tools/collect_platform_data.py` on each target machine. The zip includes:

- GPU/APU identity and `GPUConfigurationVariable`;
- X5000/X6000 kexts, PlugIns, Info.plists and firmware resources;
- GL/MTL driver images and symbols (for graphics regressions);
- ioreg media/VideoToolbox properties and `ffmpeg -hwaccels`.

Run on:

- 15.8.1 Renoir baseline;
- 26.7.1 with 5800H and 7730U;
- any Raven/Picasso/Raven2 available.

## Safety rules

- `-NRedVDA` must be opt-in; default off.
- Media and graphics flags must be independent.
- In Phase 1, `-NRedVDA` only enables logging and diagnostics. Do not add MMIO, firmware loads or engine
  writes without going through Phases 2 and 3.
- If firmware/ring bring-up fails, fall back to software decode; never panic.
- Do not tie VDA to the failed global RB+ experiments.
- Do not flip `hasUVD0`/`hasVCE`/`hasVCN0` or change media enablement defaults without real hardware
  validation.

## Handoff

When starting a new session:

1. Check out `feature/vda-hardware-decode`;
2. Read this document and `docs/Device-Profile.md`;
3. Confirm the current stable graphics build and boot args; run
   `xmake f -m release -y && xmake -y` (and debug/releasedbg before handing off);
4. Phase 1 is implemented and inert. Phase 2 comes next: use `tools/collect_platform_data.py` on a target
   machine, confirm the VCN firmware/PSP/RLC load path in `HWLibs`, and keep the engine flags false until
   the firmware bring-up is validated. The development machine used for Phase 1 was a Renoir `0x1638`
   on macOS 15.8.1 (Darwin 24.6).
