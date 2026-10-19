# Device Profile / Media Capability Layer

This layer is the first step toward a single source of truth for both the Chromium rendering fix and future
VCN/UVD/VDA hardware decoding. It deliberately does **not** change the current stable behaviour.

## Why

The rendering fix and hardware decoding are different layers:

- rendering: per-pipeline `CB_COLOR_CONTROL.DISABLE_DUAL_QUAD` policy for dual-source blending;
- media: VCN/UVD engines, firmware, rings, power and VideoToolbox/VDA capabilities.

Trying to solve rendering with a global hardware RB+ disable failed on Renoir (QQ Helper still reset the
GPU with user-space patches off), and a global switch would also affect video/compositing. A device
profile keeps the two concerns separate but shares the same APU/OS selection.

## Data model

`NootedRed/DeviceProfile.hpp`:

```cpp
struct GraphicsPolicy {
    bool conditionalDualQuad; // install the per-pipeline GL/Metal fix
    bool correctHwInfo;       // apply the existing CU/SE corrections
};

struct MediaPolicy {
    bool hasUVD0;              // engine enablement (still false in Phase 1)
    bool hasVCE;
    bool hasVCN0;
    VcnGeneration vcnGeneration; // kVcn1_0 (0x0100) or kVcn2_2 (0x0202)
    const char* vcnFirmware;     // embedded VCN blob: ativvaxy_rv.dat / ativvaxy_nv.dat
    uint32_t vcnRingSize;        // future VCN ring allocation, bytes
    uint32_t vcnFenceSize;       // future VCN fence allocation, bytes
    DecodeCaps decode;           // H.264/HEVC/AV1 capability flags
};

struct Profile {
    const char* name;
    uint16_t deviceID;
    ApuFamily family;
    KernelVersion minVersion, maxVersion;
    GraphicsPolicy graphics;
    MediaPolicy media;
};
```

The media data is populated now that Phase 1 of the VDA plan is implemented, but every profile keeps
`hasUVD0 = hasVCE = hasVCN0 = false`. The engine flags are enablement, not capability: they only flip after
the firmware/ring bring-up exists and has been validated on hardware.

## Selection

`DeviceProfile::current()` selects by `NRed::getDeviceID()`:

| device ID | profile |
| --- | --- |
| 0x1636 | Renoir |
| 0x1638 | Renoir / Green Sardine |
| 0x164C | Cezanne |
| 0x15E7 | Barcelo |
| 0x15DD | Raven |
| 0x15D8 | Raven2 / Picasso |

An unknown/not-yet-populated device uses a fallback profile with the graphics policy enabled and all media
disabled.

## Media capability data

Phase 1 records the media capability data per family; the engine enablement flags stay `false` for every
profile.

| device ID | profile | VCN | firmware | H.264 | HEVC | AV1 | engines |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0x1636 | Renoir | 2.2 (`0x0202`) | `ativvaxy_nv.dat` | yes | yes | no | off |
| 0x1638 | Renoir / Green Sardine | 2.2 (`0x0202`) | `ativvaxy_nv.dat` | yes | yes | no | off |
| 0x164C | Cezanne | 2.2 (`0x0202`) | `ativvaxy_nv.dat` | yes | yes | no | off |
| 0x15E7 | Barcelo | 2.2 (`0x0202`) | `ativvaxy_nv.dat` | yes | yes | no | off |
| 0x15DD | Raven | 1.0-class (`0x0100`) | `ativvaxy_rv.dat` | yes | yes | no | off |
| 0x15D8 | Raven2 / Picasso | 1.0-class (`0x0100`) | `ativvaxy_rv.dat` | yes | yes | no | off |

The VCN generation is the major/minor IP version; the values match the `ipVersion` argument that `HWLibs`
currently passes to the firmware loader (`0x0100`/`0x0202`), but Phase 1 only records the data and does not
load any firmware. The generation-to-family mapping follows the Linux AMD hardware component list
(Renoir/Cezanne/Barcelo are VCN 2.2; Raven/Picasso are VCN 1.0 and Raven2 is VCN 1.0.1, which share the
`0x0100` VCN 1.0 family code in `MediaPolicy`).

## Integration points

- `UserPatches::processPatcher()` logs the profile and can disable the rendering fix through
  `graphics.conditionalDualQuad`.
- `X5000::wrapSetupAndInitializeHWCapabilities()` reads `hasUVD0/hasVCE/hasVCN0` from the profile instead
  of hardcoding `false`. The effective values are also gated by `VDA::mediaEnginesEnabled()`, which is
  `false` unless the user opted in with `-NRedVDA` *and* the engine bring-up reported ready. Since all
  profiles keep the flags false, current behaviour is unchanged.
- `VDA::init()` parses the opt-in `-NRedVDA` boot argument (default off), and
  `VDA::processPatcher()` logs the media policy. When `-NRedVDA` is set it also publishes
  `NRedVDARequested`, `NRedVDAMediaEnabled` and `NRedVCNGeneration` on the iGPU for diagnostics. Phase 1
  enables no engine, and the default (no boot argument) path only logs under `-NRedDebug`.
- The VDA work adds the remaining engine bring-up; the rendering fix remains per-pipeline and does not
  need to know about decode.

## Adding a new APU

1. Add a `Profile` entry with the device ID and family.
2. Keep `conditionalDualQuad` only if the APU is in the validated family.
3. Fill its `MediaPolicy` capability data, but only flip `hasUVD0`/`hasVCE`/`hasVCN0` after the engine
   bring-up is implemented and tested on that APU.
4. Verify with the profile log and the existing rendering tests.

## Adding a new macOS version

The current profile table is device-wide; OS-specific patch data still lives in `UserPatches`/future
`PatchSet` entries. When the table becomes version-aware:

- add a profile entry with a Darwin version range;
- add the corresponding patch set/signature data;
- keep media and graphics feature flags independent.

## Hardware decoding (future VDA)

Phase 1 (capability skeleton) is implemented: `MediaPolicy` carries the VCN generation, firmware name,
ring/fence sizes and H.264/HEVC/AV1 capabilities, the profiles are populated, and `-NRedVDA` exists as an
opt-in that currently only logs. The remaining VCN path needs, at minimum:

- Phase 2: PSP/RLC firmware bring-up and VCN firmware load, with engine status read-back;
- Phase 3: VCN rings, doorbells and command submission; only then `hasVCN0 = true` for the tested profile;
- Phase 4: VideoToolbox/VDA capability exposure and surface/format handling.

Those will be implemented as media work behind `MediaPolicy`, so the Chromium fix can remain enabled or
disabled independently.

## Current status

- `DeviceProfile` skeleton: implemented.
- Graphics policy: wired into `UserPatches`; current profiles keep it enabled.
- Media policy: capability data populated; `X5000` gates the engine flags behind `VDA::mediaEnginesEnabled()`,
  which stays `false` in Phase 1, so no behaviour change.
- `-NRedVDA`: parsed and logged, default off, no hardware action.
- Build: passes (release, debug, releasedbg).
- Runtime/reboot validation: pending; Phase 1 must be booted once to confirm no graphics regression.
