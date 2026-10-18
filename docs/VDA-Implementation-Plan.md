# VDA / Hardware Video Decode — Implementation Plan

This branch is the dedicated VDA/VCN workstream. It builds on the `DeviceProfile`/`MediaPolicy`
layer from `feature/device-profile`.

## Current state

- `DeviceProfile::MediaPolicy` exists but every profile has:
  - `hasUVD0 = false`
  - `hasVCE = false`
  - `hasVCN0 = false`
- `X5000::wrapSetupAndInitializeHWCapabilities()` already reads those fields from the profile, so
  media enablement has a single switch point.
- Renders/Chromium fix is independent: `-NRedGLFix` remains a graphics-only policy.
- No VDA/VCN hardware decode is enabled yet.

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

### Phase 1 — media capability skeleton

- Extend `MediaPolicy` with:
  - `vcnGeneration`
  - firmware name(s)
  - ring/fence sizes
  - decode capability flags (H.264/HEVC/AV1 if applicable)
- Keep all profiles disabled.
- Add a `-NRedVDA` boot argument (default off) separate from `-NRedGLFix`.
- Verify no graphics regression.

### Phase 2 — firmware / PSP bring-up

- Confirm VCN firmware names per family (the tree already references `ativvaxy_rv.dat` for VCN 1.0 and
  `ativvaxy_nv.dat` for VCN 2.1 in HWLibs).
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
- If firmware/ring bring-up fails, fall back to software decode; never panic.
- Do not tie VDA to the failed global RB+ experiments.
- Do not change `MediaPolicy` defaults without real hardware validation.

## Handoff

When starting a new session:

1. Check out `feature/vda-hardware-decode`;
2. Read this document and `docs/Device-Profile.md`;
3. Confirm the current stable graphics build and boot args;
4. Start with Phase 1 unless data from a target machine is already available.
