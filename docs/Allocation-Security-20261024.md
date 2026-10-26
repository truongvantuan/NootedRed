# GPU allocation and security follow-up, 24 October 2026

The guarded diagnostic RELEASE has booted and completed a recorded 133-second
system sleep/wake with normal user-confirmed devices and automatic Wi-Fi rejoin.
Current UUID is `8E3E2229-FE15-3AC6-ACBC-FFD54C1F96E5`; the previous production
RELEASE `4D15A2C3-9275-3AF0-A9B3-D1FD18D4EF5B` is checkpointed. Allocation
warnings remain substantial and their post-wake clients/root cause are unresolved.
Detailed capture across wake is incomplete; independent post-wake verification
is saved. Allocation policy is unchanged. Full SIP remains a separate, uninstalled
candidate. See the completed verification at the end of this report.

## What the existing evidence establishes

The 12:26 capture contains **2061 native allocation-error records** between
12:21:39 and 12:24:20. One failed request is 26,804,224 bytes while the diagnostic
reports 80,891,840 general-free and 451,080,128 fixed-free bytes. These are
separate allocator statistics. Their presence does not prove the requested
alignment, pool, placement or contiguous span can be satisfied. It also prevents
concluding that every failure simply means all 512 MiB of reserved VRAM is used.
Fragmentation, placement restrictions, retry/reclaim behavior and request origin
remain hypotheses, not established causes.

Offline inspection of the exact 24H32 Apple driver identifies the emitter as
`AMDHWMemory::allocateLargeBlocks`, called from `AMDAccelVidMemory::allocPhysical`.
The emitter returns false on the observed failure path. However, `allocPhysical`
can return false on other control paths, so its return alone is not an allocation
error. Resource `pageon` returns **void**; a synthetic success result would be an
ABI error. The new trace observes all three methods with those exact signatures.

The working production profile previously passed seven native GL/Metal/compute
and H264/HEVC decode/encode cases before and after a recorded system sleep/wake.
The warnings therefore are not, by themselves, evidence that those cases failed.
They remain worth investigating for repeated reclaim/retry work. Native failure,
application-visible failure and a GPU reset are distinct observations.

A passive 14:36 snapshot reports approximately 160 MiB VRAM free, 269 MiB video
memory in use and 47 MiB system/GART memory in use. Duplicate registry records
refer to the same physical accelerator and must not be summed. These counters
are instantaneous; they are not simultaneous measurements of the 12:21 burst.
The approximately 11 GiB GART address space does not increase the BIOS's 512 MiB
reserved VRAM. No VRAM spoof or false-success allocator patch is installed.

## Diagnostic build and scope

The staged NootedRed remains **RELEASE**, UUID
`8E3E2229-FE15-3AC6-ACBC-FFD54C1F96E5`, executable SHA256
`a54fe05618fca950d0bda79799b4709e22e4439ba1d1dea1dac3c3bc071854e1`.

The opt-in `-NRedAllocTrace` requires Darwin 24, the exact native X5000 UUID
`41C43219-294B-3932-B77E-68824533E800` and all three 32-byte entry prefixes before
routing. A partial installation leaves any installed wrapper transparent.
Expected IORegistry markers are `NRedAllocTraceVersion=1`,
`NRedAllocTraceRoutes=7`, `NRedAllocTraceEnabled=1`.

It forwards each native invocation once with unchanged arguments and return
values, records the first 128 actual failed allocator requests and the first
four call stacks, and correlates them with physical-allocation outcomes and
resource paging-state words. Fixed bookkeeping has 32 slots and no diagnostic
lock is held while invoking native code or logging. Observation can affect
timing; no claim of zero overhead is made. Current-process identity may be a
kernel worker rather than the app that originally requested the resource.
Symbolization checks loaded UUIDs and labels nearest-symbol inference explicitly.
Quota exhaustion or missing pairs is reported as incomplete evidence.

All **19 host checks pass**, including sanitizer execution of the actual
installer/wrappers, unsupported-driver negative controls, argument/return
preservation, nested/overflow bookkeeping, bounded output and capture-parser
negative controls. These checks do not establish runtime hook compatibility;
the next boot is required. OpenCore's matching validator passes.

Only two EFI files changed: `OC/config.plist` (adds the diagnostic argument) and
`OC/Kexts/NootedRed.kext/Contents/MacOS/NootedRed`. Uncached USB reads verify all
111 resulting files. OpenCore stays RELEASE; GPE/USB/audio/Wi-Fi, graphics/media
flags, identity and security policy are retained. The full checkpoint is:

`/Users/tvtuan/EFI-Backups/OPENCORE-before-allocation-trace-20261024-143609/EFI`

After rebooting from **OPENCORE**, run promptly:

```sh
bash /Users/tvtuan/Github/NootedRed/build/allocation-security-20261024/record-wake.sh
```

The script verifies the loaded build and existing code patches, starts passive
kernel capture, then prompts for Apple menu → Sleep, a roughly 30-second wait
and physical wake. It records actual OS sleep/user-wake counter transitions and
post-wake evidence. It does not submit GPU stress workloads, force sleep or
reboot. Desktop, menus, USB, speaker and Wi-Fi function still need physical
confirmation. Bluetooth remains outside this investigation.

If startup consumes the sample quota, the script retains those failures and
stops short of requesting a wake. A nonzero result can mean capped/incomplete
trace evidence; inspect its saved summary before interpreting it as a hardware
failure. Do not repeatedly provoke hangs to fill the trace.

Rollback restores exactly the verified production binary and arguments, with
manifest guards against overwriting subsequent EFI work:

```sh
python3 /Users/tvtuan/Github/NootedRed/build/allocation-security-20261024/stage-trace.py --rollback
```

Rollback takes effect on the following boot. Staging and readback were exercised;
rollback has not been physically tested through a failed boot.

## Security findings and platform limits

| Layer | Current evidence | Follow-up |
| --- | --- | --- |
| SIP | `csr-active-config=030a0000` (0xA03): allowances for untrusted/unapproved kexts, unprotected filesystem and unauthenticated root. Debugging, DTrace, NVRAM and BaseSystem restrictions report enabled. | Full-SIP candidate changes only CSR to `00000000`, outside EFI. Compatibility remains unproven. Restore the production binary/arguments before that isolated test. |
| System volume | Root snapshot reports **Sealed: Yes**, mounted read-only; authenticated-root enforcement reports **disabled**. No OCLP root-patch metadata was found. | A present seal/read-only mount does not prove enforcement is enabled. These findings support an isolated trial, not a compatibility guarantee. |
| Gatekeeper | Assessments enabled. | Retain. No AMFI, signing or sandbox bypass was added for diagnostics. |
| FileVault | Off. | Data-volume encryption is a separate project requiring a recovery-key and preboot-unlock plan. It does not fix GPU allocations. |
| OpenCore Apple Secure Boot | `SecureBootModel=Disabled`. | Separate trial after SIP validation. The pinned 1.0.9 manual maps `Default` to SMBIOS and lists `j137` for iMacPro1,1. Inspect boot manifests and injection compatibility before enabling; not changed here. |
| OpenCore Vault | `Optional`; no enforced signed vault. | A signed vault needs a signed manifest and a key embedded in OpenCore. It is distinct from Apple/UEFI Secure Boot and would need maintenance whenever EFI changes. Not enabled here. |
| Recovery/scan | `DmgLoading=Signed`; `ScanPolicy=0`; `ExposeSensitiveData=6`. | Signed recovery images retained. ScanPolicy currently permits broad discovery. Exposure 6 reveals OpenCore version in NVRAM/picker, not the booter path or OEM dump. Neither is a GPU/performance fix. |
| Firmware trust | No verified end-to-end firmware Secure Boot chain was established by this capture. | Do not infer firmware enforcement from OpenCore settings or enroll keys silently. |
| Virtualization | BIOS SVM enabled, but current `kern.hv_support=0`. | Apple's Hypervisor capability is unavailable in this running configuration. A graphics boot argument does not establish support. |
| Memory/hardware | BIOS maximum reserved GPU memory is 512 MiB; 32 GiB system RAM. | Preserve real limits; investigate failed allocation constraints instead of advertising invented VRAM. |
| Wireless | Intel 8265 with the Sequoia AirportItlwm fork. | Its documented AWDL/AirDrop and WPA3-only/mandatory-PMF/MLO limits remain driver limits. Current functional Wi-Fi and automatic wake rejoin previously passed. |

The uninstalled full-SIP-only candidate has SHA256
`b0e624a2e545112bc767f12182b204cb6a194cbd8dde3cf2e446dd2bbccf6607` and passes
`ocvalidate`. Before using it, restore and verify the production profile, then
change only CSR. Acceptance requires actual SIP and authenticated-root status,
all expected injected kexts, graphics/media code-page checks, native output and
physical sleep/wake/device checks. Do not combine that experiment with the
allocation trace, SecureBootModel, Vault or FileVault changes.

Primary references: [Apple SIP](https://support.apple.com/guide/security/system-integrity-protection-secb7ea06b49/web),
[Apple signed system volume](https://support.apple.com/guide/security/signed-system-volume-security-secd698747c9/web),
[the exact OpenCore configuration manual](https://github.com/acidanthera/OpenCorePkg/blob/6d8490d3236ad27d5b39063e0ebb55a79272d7a4/Docs/Configuration.tex),
and [the Wi-Fi fork's documented limits](https://github.com/laobamac/itlwm#airportitlwm-on-macos-sequoia).

Private logs, security snapshots, host-test results, source/artifact hashes,
deployment manifests and the separate SIP candidate are under
`build/allocation-security-20261024/`. The native disassembly and retained warning
sample are under `build/postinstall-audit-20261024/`. No runtime fix or security
hardening success is claimed before the relevant isolated boot evidence exists.

## First diagnostic boot: current results

Boot session `34E695DC-11E0-46D9-9CB5-855E82D9EBD8` loaded the expected
`8E3E2229-FE15-3AC6-ACBC-FFD54C1F96E5` RELEASE, all three trace routes and all
15 configured executable kexts. The 111-file staged EFI readback matches.
Before/after passive graphics and media code-page checks pass; NotificationCenter
signed pages remain valid. No GPU reset, hang or new GPU/WindowServer report was
observed in these checks. This collection does not repeat the seven native
render/media workloads.

Ninety saved failed allocator requests have matching native physical-allocation
failure returns: 49 requests of 15 MiB in WindowServer's context, and 41 smaller
requests in mediaanalysisd's context. Saved stacks identify command-queue batch
resource preparation, memory-map preparation and memory wiring before
`allocPhysical`. Those WindowServer failures occurred 118–142 seconds after
boot, before the sleep prompt. The native false result propagates through the
observed wire/prepare path according to the exact driver disassembly; the final
command-queue/application outcome is not measured. These samples do not prove
which fork or EFI change introduced the underlying allocator behavior.

Runtime stack addresses differ from the module listing by a consistent observed
`0xB000000`. Correlation uses two exact return sites in the matching NootedRed
UUID (`0xe2e6` after OSBacktrace and `0xdd8a` after the original physical allocator
call), agreed by all four saved stacks, plus the exact UUIDs of native modules.
This is an inferred address normalization, not a direct kernel-slide API result.
Nearest native symbol names remain explicitly approximate. See
`ADDRESS-CORRELATION-private.json` and saved machine-code disassembly.

The unified log contains 6646 native warning records over this boot by the first
corrected query, exceeding the 90 detailed saved requests. The bounded trace and
log retention therefore do **not** provide complete attribution for every
warning. The collector now reports that coverage gap rather than calling it a
complete trace. Lack of a retained quota marker is not proof the quota was never
reached. No allocator-policy fix is justified by these data yet.

The first collector missed Lilu detail records that were present in `dmesg` but
absent from its unified-log query. It now ingests session-verified before/after
kernel rings and a bounded live ring capture, with negative controls for stale
boot identity, failed capture and file containment. A second collection exposed
that detaching the privileged ring helper loses terminal-scoped sudo credentials;
the helper now retains its terminal, proves a successful read before prompting
for sleep, and saves explicit errors. The parent refreshes its existing sudo
ticket during the wait and reauthenticates before final capture. These fixes
change capture tools only; the kext binary, EFI and security policy are unchanged.

The user initially clarified that no sleep test had been performed. A later
normal-device report also had no matching OS sleep/wake transition at capture
time; it is retained as a user report rather than proof of system sleep. Fresh
capture `wake-20261024-151655-4450` is running for a controlled test. Caffeine
holds an idle-display assertion, but that alone does not prove it blocked an
explicit system-sleep request. No sleep or wake failure cause is established
from an absent transition.

## Completed system sleep/wake verification

The user authorized a direct `sudo pmset sleepnow` request after menu tests had
no recorded transition. It was issued at 15:22:22. macOS records Software Sleep
at **15:22:35**, DarkWake at **15:24:47** and FullWake at **15:24:48**: one
**133-second** cycle, counters Sleep/DarkWake/UserWake **1/1/1**, unchanged boot
session. The user then confirmed normal desktop/menus, usual USB, PC speaker and
automatic Wi-Fi rejoin. Current Wi-Fi has IPv4 and passes a connectivity test
bound to its interface; AppleALC and codec devices are present. These physical
confirmations supplement the helpers' conservative enumeration-only fields.

Fresh post-wake checks verify the same diagnostic RELEASE UUID, three active
trace routes, expected GL/shared-cache/media patch bytes and NotificationCenter's
904 signed pages. NotificationCenter is at 0.0% CPU. There is no observed GPU
reset/hang or new GPU/WindowServer report. All 111 staged EFI files still match.
The native render/compute/codec workload suite was not repeated during this
passive collection. No EFI/security setting changed during this verification;
full SIP remains an uninstalled separate candidate.

**Residual allocation warnings remain substantial.** The current-boot query from
FullWake through 15:33:52 contains **24,228 native allocation-warning records**.
15,726 request 26,607,616 bytes. General-free figures vary from 798,656 to
322,338,752 bytes; the separate fixed-free figure remains 451,080,128 bytes.
These statistics cannot be added into one pool or used to identify a causal app.
The post-wake warning clients are not proven by the earlier 90 detailed samples.
The successful wake therefore establishes tested device usability, not an
allocation fix or optimal performance.

The live ring captured 4019 native warning lines before failing at 15:22:24 with
`sudo: ignoring time stamp from the future` and a credentials request. Thus the
original automatic collector's failure/`OS_wake_observed=false` describes its
capture failure, not a failed system wake. That raw result is preserved. Fresh
post-wake checks, complete power-transition logs and the user's actual post-wake
confirmation establish the completed cycle independently. Detailed trace
coverage across wake remains incomplete. The parser can explicitly analyze
successful same-boot samples preceding a read error while retaining those errors
and returning an incomplete result. A reader or credential refresh failure no
longer aborts independent OS-transition observation in future runs.

Consolidated evidence:
`build/allocation-security-20261024/RUNTIME-VERIFICATION.json` and
`wake-20261024-151655-4450/FINAL-VERIFICATION.json`. The separate
`POSTWAKE-KERNEL-SUMMARY.json`, `POSTWAKE-ALLOCATION-DISTRIBUTION.json`,
`POSTWAKE-USER-CONFIRMATION.json`, `postwake-verified/`, `audio-postwake/`,
`wifi-postwake/` and `trace-recovered/` retain the supporting observations and
coverage limitations. Allocation root cause and a safe allocator-policy change
remain unresolved; no false-success patch or log suppression was applied.
