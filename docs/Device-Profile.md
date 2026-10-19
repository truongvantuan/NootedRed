# Device Profile / Media Capability Layer

This layer is the hardware half of the compatibility model described in
[Compatibility Architecture](Compatibility-Architecture.md): it is a single source of truth for per-device
graphics and media capabilities. It deliberately does **not** contain patch bytes or per-macOS-build data;
binary-target data is the other half of the model and will be selected by the identity of the binary being
patched.

## Why

The rendering fix and hardware decoding are different layers:

- rendering: per-pipeline `CB_COLOR_CONTROL.DISABLE_DUAL_QUAD` policy for dual-source blending;
- media: VCN/UVD engines, firmware, rings, power and VideoToolbox/VDA capabilities.

Trying to solve rendering with a global hardware RB+ disable failed on Renoir (QQ Helper still reset the GPU
with user-space patches off), and a global switch would also affect video/compositing. A device profile keeps
the two concerns separate but shares the same APU selection.

The profile is keyed by device ID only and is deliberately small: adding an APU must never duplicate patch
data, and adding a macOS build must never duplicate hardware facts. The two axes are orthogonal; see the
architecture document for the target-identity half.

## Data model

`NootedRed/DeviceProfile.hpp` (Milestone 1 of the compatibility architecture):

```cpp
struct GraphicsPolicy {
    bool  conditionalDualQuad; // install the per-pipeline GL/Metal fix
    bool  correctHwInfo;       // apply the existing CU/SE corrections
    bool  rbPlusAllowed;       // APU-level RB+ capability (logged; becomes a site precondition)
    UInt8 numShaderEngines;    // value written by the GL HwInfo correction (APU fact, not a patch byte)
};

struct MediaPolicy {
    bool   hasUVD0;
    bool   hasVCE;
    bool   hasVCN0;
    UInt16 vcnGeneration;      // 0x0100 = VCN 1.0, 0x0202 = VCN 2.2
    const char* vcnFirmware;
    UInt32 vcnRingSize;
};

struct Profile {
    const char* name;
    UInt16 deviceID;
    ApuFamily family;          // Raven, Raven2, Picasso, Renoir, RenoirE, GreenSardine, Cezanne, Barcelo
    SupportLevel level;        // unavailable / experimental / validated (coarse roll-up)
    KernelVersion minVersion, maxVersion;
    GraphicsPolicy graphics;
    MediaPolicy media;
};
```

Current media fields are all `false`: this is intentional. They are the capability surface for the VDA
work, not a claim that decoding works. `vcnGeneration` is `UInt16` because it has to hold `0x0202`.

`level` is a coarse, per-profile roll-up for logging, and it stays `experimental` while media is disabled.
The authoritative per-feature level is generated from the compatibility manifest (see the architecture
document). The only hardware-validated combination today is the conditional GL/Metal fix on macOS 15.8.1 /
Renoir `0x1638`; that is a per-build fact, so it is recorded in the support matrix rather than in this
version-wide table.

## Selection

`DeviceProfile::current()` selects by `NRed::getDeviceID()` and `currentKernelVersion()`:

| device ID | profile | level |
| --- | --- | --- |
| 0x1638 | Renoir / Green Sardine | experimental (GL/Metal fix validated on 15.8.1 only) |
| 0x1636 | Renoir | experimental |
| 0x164C | Cezanne | experimental |
| 0x15E7 | Barcelo | experimental |
| 0x15DD | Raven | experimental |
| 0x15D8 | Raven2 / Picasso | experimental |

`forDevice(deviceID, version)` returns `nullptr` when the device is unknown or the kernel version falls
outside the profile's `[minVersion, maxVersion]` window. `current()` falls back to the generic profile, which
keeps the graphics policy enabled and all media disabled, so an unknown combination never enables media.
The version window is metadata for now: per-build data is keyed by binary identity, not by this range.

Note: `NRed::processPatcher()` still panics on an unknown device ID, so the fallback is effectively
unreachable for devices not in the table. The unknown-device no-op policy is Milestone 2 of the
architecture document.

## Integration points

- `UserPatches::processPatcher()` logs the profile and can disable the rendering fix through
  `graphics.conditionalDualQuad`.
- `X5000::wrapSetupAndInitializeHWCapabilities()` reads `hasUVD0/hasVCE/hasVCN0` from the profile instead of
  hardcoding `false`. Since all profiles keep them false, current behaviour is unchanged.
- `DeviceProfile::logCurrent()` emits one canonical line per boot and publishes the same facts as IORegistry
  properties (`NRedCompatDeviceID`, `NRedCompatFamily`, `NRedCompatLevel`,
  `NRedCompatNumShaderEngines`, `NRedCompatVCNGeneration`).

Example log line:

```text
Compat: profile="Renoir/Green Sardine" family="Green Sardine" level=validated device=0x1638 rev=0xC5
darwin=24.6 graphics{dualQuad=1 hwInfo=1 rbPlus=1 numSE=1} media{gate=0 vcn=0x0000 fw=none}
```

VDA work will add `MediaPolicy` values and the corresponding engine bring-up; the rendering fix remains
per-pipeline and does not need to know about decode.

## Adding a new APU

1. Add a `Profile` entry with the device ID and an explicit family (do not alias Cezanne/Barcelo to an
   existing family).
2. Set `level` to `experimental` until the combination is actually validated on hardware.
3. Keep `conditionalDualQuad` enabled only if the APU belongs to the validated family.
4. Fill `rbPlusAllowed` and `numShaderEngines` from a real capability source (register/IP probe preferred);
   do not guess from the device ID alone.
5. Add media capabilities only after the engine bring-up is implemented and tested.
6. Verify with the canonical profile log and the existing rendering tests. Never treat a code-level entry as
   a hardware validation claim.

## Adding a new macOS version

The current profile table is device-wide; OS-specific patch data lives in the patch-set/target tables, not
in this file. When adding a macOS build:

- collect the target binaries with the platform data collector and add the target-identity data (see
  [Compatibility Architecture](Compatibility-Architecture.md));
- add the generated patch data and its validation status;
- keep media and graphics feature flags independent.

Do not widen `minVersion`/`maxVersion` as a substitute for target data: the version window only decides which
profile is selected, not whether a patch matches.

## Hardware decoding (future VDA)

The future VCN path needs, at minimum:

- correct VCN generation and firmware (for example `ativvaxy_nv.dat` for VCN 2.1/2.2);
- PSP/RLC firmware, rings and power;
- `hasVCN0 = true` in the profile;
- VideoToolbox/VDA capability exposure and surface/format handling;
- a decided architecture for VCN 1.x APUs (Raven/Raven2/Picasso), which cannot use the X6000 VCN2 engine.

Those will be implemented as media work behind `MediaPolicy`, so the Chromium fix can remain enabled or
disabled independently.

## Current status

- `DeviceProfile` v2 (Milestone 1): implemented — capability fields, explicit Cezanne/Barcelo families,
  version-aware lookup, compile-time table invariants, canonical compat log.
- Graphics policy: wired into `UserPatches`; current profiles keep it enabled.
- Media policy: wired into `X5000`; all values false, so no behaviour change.
- Build: passes.
- Runtime/reboot validation of the new log line and properties: pending.
