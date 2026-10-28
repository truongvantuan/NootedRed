# Boot watchdog failure — 27 October 2026

Six failed boots this morning produced twelve `watchdogd` crash reports and six
kernel panic reports. The user reported forcing restarts and no EFI/BIOS changes.
The immediate failure is the stock daemon's missing-IOWatchdog assertion, not
the earlier Zalo/WindowServer GPU-hang signature. A startup-publication race was
found in the installed VirtualSMC and a candidate correction has been staged
with user approval. Boot reliability is not yet verified.

## Incident evidence

Evidence is local in `build/boot-watchdog-20261027-0814/`, including copied
reports, decoded stackshots, instruction comparisons and current service state.

- Each failed boot has daemon crashes near 8 and 18 seconds uptime, followed by
  a panic stackshot around 28–29 seconds. The panic names another `watchdogd`
  instance exiting with signal 4.
- All twelve daemon reports have fault offset `0xcbb1`. Their captured
  instruction windows exactly match the current signed Apple executable.
  The opcode is intentional `ud2`, following `_os_crash` with the string
  `connect_to_kext() unexpectedly failed - unable to lookup watchdog KEXT service`.
  This is not evidence of an unsupported AMD CPU instruction.
- The matching caller attempts `IOServiceGetMatchingService` for `IOWatchdog`.
  This differs from an IOServiceOpen failure and from GPU watchdog recovery.
- Apple's unmodified launch job has `KeepAlive.SuccessfulExit=false` and
  `_PanicOnCrash.PanicOnConsecutiveCrash=true`; repeated daemon failures lead to
  a kernel panic. The job and watchdog protections were not disabled or edited.
- Report filenames/creation times are not the panic's actual execution time.
  The 08:12:17 report embeds a stackshot from the previous failed boot at
  08:10:56. The current successful boot began 08:12:09, UUID
  `802A41CA-6AE0-4AB1-86CA-254F7F4DCEA0`.
- On the successful boot, `SMCWatchDogTimer` is active and its
  `IOWatchdogUserClient` names the running daemon PID 114. launchctl shows one
  daemon run. EndpointSecurity denial messages also occur on this healthy boot;
  they do not explain the captured missing-service assertion.
- The same trap offset and missing-service failure occurred on 26 October,
  before the latest NootedRed context/VM tracing build. That does not exclude
  timing interactions, but prevents attributing the signature solely to the
  latest tracing changes.

## VirtualSMC defect and candidate correction

The installed VirtualSMC 1.3.9 UUID is
`FF5A572E-92BF-3E3C-B1EC-08490161216A`. Its disassembly contains:

- Servicing path: store `servicingReady=true`, then read `mmioReady`.
- MMIO callback: read `servicingReady`, then store `mmioReady=true`.

Those operations match the source at pinned upstream commit
[`b5c62c2311540c529c00996d0d9cec33f8e571c9`](https://github.com/acidanthera/VirtualSMC/tree/b5c62c2311540c529c00996d0d9cec33f8e571c9).
There is a legal interleaving where the callback reads false, servicing stores
true and reads false, and the callback finally stores true. Neither publishes
the service. Another legal interleaving publishes twice. These problems occur
even under sequential consistency; simply strengthening the old atomic loads
would not fix their ordering.

The candidate replaces the two booleans with one readiness bitset and an
acquire/release atomic read-modify-write. Only the transition to both-ready owns
publication. Duplicate notifications cannot publish twice. First-generation
initialization signals both readiness bits and keeps its MMIO-independent path.
The winning service publishes diagnostic properties `StartupReadinessGate=1`
and `StartupReadyFlags=3`.

The defect is demonstrated in code, but a failed boot did not retain the actual
readiness values. Its causal role in these incidents remains a candidate until
controlled boot testing; allocation, matching and other initialization failures
are not excluded.

Validation completed:

- All six legal orderings of the old operations: one missed publication, one
  duplicate and four single publications.
- Actual candidate helper: all notification strings through length eight,
  duplicate callbacks, legacy generation and 2,000 concurrent producer starts.
  ThreadSanitizer reported no failure; the last producer also observes the
  other's initialized payload.
- x86_64 RELEASE build succeeded. Its undefined kernel-import set is identical
  to the installed binary. Source helper and tested helper are byte-identical.
- The active VirtualSMC was checked against the inspected reference, and the
  unchanged OpenCore config passes 1.0.9 validation.

Patch: [startup-readiness.patch](../tools/patches/virtualsmc/startup-readiness.patch).
Host verification: `python3 tools/test_virtualsmc_startup_readiness.py`.
No kext or GPU workload is executed by that host test.

## Deployment and remaining verification

After the user selected “Ready; stage the candidate,” only these EFI files
changed:

- `OC/Kexts/VirtualSMC.kext/Contents/Info.plist`
- `OC/Kexts/VirtualSMC.kext/Contents/MacOS/VirtualSMC`

The new candidate UUID is `556F477A-93E6-319A-9E07-4194AD44DCF5` and executable
SHA-256 is `2734ac872973ccb9811237dd3dc0243f7146f562c7d539674f387165aeeca138`.
It retains module version 1.3.9 and is a local candidate, not an official release.
NootedRed, other kexts, boot arguments, config sections and system files remain
unchanged. Full backup:
`~/EFI-Backups/INTERNAL-before-vsmc-readiness-20261027-083247/EFI`.

Reboot manually, then collect without running the Zalo/GPU experiments:

```sh
bash /Users/tvtuan/Github/NootedRed/build/boot-watchdog-20261027-0814/collect-after-boot.sh
```

The collector verifies the candidate UUID, readiness markers, SMC watchdog
service/user client, daemon run count and any daemon crashes matching this boot
UUID. A successful single boot is not proof of reliable cold startup. Multiple
controlled cold boots/restarts and normal device checks remain necessary.
`build/boot-watchdog-20261027-0814/restore-vsmc.py` restores only the saved
VirtualSMC after verifying its current identity; the correct internal ESP must
be mounted writable first. No reboot was initiated by the assistant.

## First candidate boot — 27 October, 09:07

Collected at 09:11:32 in
`build/boot-watchdog-20261027-0814/boot-20261027-091131/`.
Current boot UUID: `1B38CF9C-A1C5-4B80-9B22-870B21666475`.

- Candidate UUID `556F477A-93E6-319A-9E07-4194AD44DCF5` is loaded.
- Both readiness properties match the expected values (gate 1, flags 3).
- SMCWatchDogTimer is present; its user client belongs to the running watchdogd.
- launchctl records one daemon run; no watchdogd crash reports match this boot.
- The kernel ring was captured. No matching current-boot Kernel or WindowServer
  JSON diagnostic report was found in the additional report check.
- The user confirmed desktop/menus, usual USB ports, PC speaker and Wi-Fi all
  work normally.

This verifies the candidate's first observed boot and normal device operation.
It does not establish repeatable startup reliability or resolve the separate
intermittent HEVC/Zalo hang. Additional controlled restarts and cold boots remain
necessary; none were initiated during this verification.
