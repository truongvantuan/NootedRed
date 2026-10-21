# DisplayPort recovery candidate (0.9.4)

`-NRedDPFix` opts into experimental receiver-power sequencing and a bounded transmitter BIOS
loop. **0.9.3 failed monitor power-button recovery; 0.9.4 is awaiting hardware verification.**
It currently supports only Renoir with Sonoma 14.8.9 `23J631`
and X6000Framebuffer UUID `2A0EC5C3-7355-3063-BCCE-E15CF7E02A0C`. Other images leave the hook
uninstalled. GLFix and the VDA bridge remain available.

## Evidence and hypothesis

The user's MG27S9Q monitor fails to reconnect after its own power button is switched off/on.
Three captures reproduce failed HBR2 x4 training, then an HBR2 x2 attempt whose display-policy
thread remains busy inside ATOM command execution. All captures show the same register-reading
call path, with a full CPU core occupied. The later captures also show IOGraphicsSystem waiting
on that thread. This happens at 144 Hz and at 60 Hz, both with and without `-NRedDPDelay`.

The matching stock binary identifies the stuck caller as `transmitter_control_v1_6`, table
`0x4C` (`DIG1TransmitterControl` / `UNIPHYTransmitterControl`), action 1 (enable). The caller
`dcn10_link_encoder_enable_dp_output` supplies that action explicitly. The enclosing
`dp_enable_link_phy` calls receiver power control only **after** transmitter enable. A hang
inside transmitter enable therefore prevents reaching that receiver-wake call.

Hypothesis: receiver D3 retained during reconnect contributes to the first training failure;
waking and checking the sink before transmitter enable may prevent the subsequent hang.
The existing captures do not record DPCD 0x600, so they do not prove this hypothesis. All
three boots also had earlier compute-queue GPU resets, which remain a possible trigger.

## Implementation

The opt-in hook surrounds `dp_enable_link_phy` and affects direct DP signal 0x20 only.
Before calling the original function with unchanged arguments, it reads DPCD `SET_POWER`
(0x600). If D0 is already reported, it makes no write. For D3 or D3-with-AUX-on it requests
D0, preserves reserved bits, waits 2 ms, and reads back the result. AUX retries are bounded
to three attempts. Unreadable/unsupported power states are logged without guessing a value.
The original driver still handles PHY enable, link training and their results.

The original BIOS operation is still attempted, and register values are never fabricated.
In 0.9.3 an underlying fault could keep that operation looping indefinitely. The 0.9.4
guard below addresses that unbounded branch loop; it does not establish successful output.

### Bounded BIOS execution in 0.9.4

Only ATOM command `0x4C`, action 1 (transmitter enable), called inside direct-DP PHY enable
receives a 20-second deadline. All seven branch opcodes share three native handlers; their
wrappers check the deadline before forwarding. Unrelated commands and threads keep their
original behavior. The guard does not bound a single operation that blocks without reaching
another branch. At most 16 concurrent DP-call scopes are tracked; exhaustion leaves native
behavior unchanged.

On expiry the guard validates the complete native frame chain (at most 64 frames) and each
table's bounds in the driver's 64 KiB BIOS image. It then redirects every instruction pointer
to EOT (`0x5B`). The original interpreter pops/frees its own frames and restores its parameter
stack. The outer wrapper returns **failure**, overriding the otherwise successful EOT result.
It does not set the native error field, whose error exit bypasses frame cleanup. Invalid frame
chains are left untouched and a refusal marker is published. No raw register writes, training
success override, permanent mode change, or periodic forced modeset is added.

All five additional entry signatures and a fingerprint of the complete 871-byte native VM
implementation must match before installing the guard. The base UUID/build/APU checks still
apply. Partial routing leaves the installed wrappers as pass-through because no guard scope
is armed until the complete set succeeds. These checks reduce ABI risk; host tests cannot
prove that kernel recovery works. A failed transmitter operation may still leave the monitor
black even when the workloop becomes available again.

| Guard entry | Offset from kext header | Inspected ABI |
| --- | --- | --- |
| ATOM execute | `0x5C9F0` | `bool(self, uint32 table, parameters*, uint32 options)` |
| Branch group 1 | `0x5C1B0` | `void(vmContext*)` |
| Branch group 2 | `0x5C1F0` | `void(vmContext*)` |
| Branch group 3 | `0x5C230` | `void(vmContext*)` |
| Register read/validation | `0x1CAD6` | `uint32(self, uint32 dwordRegisterIndex)` |

The opt-in guard records the last actual register read, table/instruction offsets and comparison
operands after an abort. The loaded BIOS image is copied to IGPU for subsequent offline table
analysis. These diagnostics are intended to identify the condition behind the training failure;
a timeout alone is not a complete DisplayPort fix.

## Hardware trial, 21 October 2026

The 0.9.3 DEBUG image was verified loaded with the expected UUID and Ready=1. The monitor
initially displayed the desktop, then stayed black after its power button was switched off/on.
At first the display-policy process remained idle and macOS still reported the monitor online.
An app-scoped 1080p60 → original 1440p60 mode cycle at 08:46:33–37 produced two fresh training
PASS results, and the user confirmed that the desktop returned without rebooting. This is a
verified manual recovery for that attempt, not an automatic fix or evidence that all hangs
can be recovered by a mode cycle.

A second power-button trial recorded a real HPD removal at 08:53:58 and insertion at
08:54:39.521. HBR2 x4 training failed at 08:54:40.803 (`lane_status=0x2800000`), followed by
an HBR2 x2 attempt at 08:54:40.808 with no completion in the observed window. The display-policy
process then consumed a full CPU core. Thus missing hotplug cannot explain this second
failure; the pre-wake candidate has not prevented the earlier training/hang phenotype.
The 09:04:45 stack capture confirms that the same 0.9.3 boot is stalled in the original BIOS
register-reading loop: all 250 samples include transmitter control and command execution,
with 4.979 seconds of display-policy CPU in the five-second capture.
The complete boot log also records a computeUQ4 hang/reset at 08:38:15–18, before this trial.
The reset had occurred before the live recorder began; its absence from that recorder alone
would be misleading. As with the previous three boots, a causal relationship is unproven.

The latest receiver diagnostic was D0 → D0, but this revision has no per-call counter or
timestamp. It must not be assigned to a specific training attempt from that marker alone.
System sleep/wake has not been validated. The next investigation is a bounded BIOS error
unwind with useful register/table diagnostics; neither blind polling nor longer AUX sleeps
is justified by the second trial.

Private ABI provenance comes from the installed stock `SystemKernelExtensions.kc`:

| Entry | Offset from kext header | ABI verified by disassembly/call sites |
| --- | --- | --- |
| `dp_enable_link_phy` | `0xC9319` | `void(dc_link*, uint32 signal, uint32 clockSource, const dc_link_settings*)` |
| DPCD read helper | `0x12471F` | `dc_status(dc_link*, uint32 address, uint8*, uint32 size)` |
| DPCD write helper | `0x124884` | `dc_status(dc_link*, uint32 address, const uint8*, uint32 size)` |

The image UUID, bounds-checked Mach-O commands and all three 32-byte entry signatures must
match before routing. AUX success is the native `dc_status` value **1**, not IOReturn 0.
There is no cross-build pattern fallback. A mismatch logs a refusal rather than panicking.

`-NRedDPDelay` remains a separate, existing post-power-call delay. The first candidate test
keeps it removed so the candidate is the only functional change relative to the latest trial.

## Verification

`python3 tools/test_dp_recovery.py` compiles the actual production policy with AddressSanitizer
and UndefinedBehaviorSanitizer. It checks D0 no-op, D3 transitions, reserved-bit preservation,
AUX failures, retries, readback failures, unsupported states, and malformed/mismatched image
refusal. On this host it also checks the actual installed stock framebuffer against the guards.
Host tests and compilation do **not** prove the sink reports D3 or that either wake case works.
`python3 tools/test_atom_loop_guard.py` additionally checks native EOT cleanup and parameter-stack
restoration in a host model, deadline boundaries, malformed-chain refusal without partial writes,
thread isolation/exhaustion, entry-point signatures and the installed interpreter fingerprint.
`python3 tools/test_atom_native_vm.py` executes the actual inspected stock interpreter and native
CallTable/branch/EOT instructions in userspace with synthetic BIOS tables and host callbacks,
checking finite execution and timeout cleanup at depths 1, 3 and 64. No GPU is accessed.

IORegistry diagnostics on IGPU:

| Property | Meaning |
| --- | --- |
| `NRedDPRecoveryRequested` | Boot argument requested the hook |
| `NRedDPRecoveryReady` | 1 only after hardware/build/binary checks and successful routing |
| `NRedDPRecoveryState` | Latest wake policy result: 1 already D0, 2 confirmed woken, 3 AUX read failed, 4 unsupported power, 5 wake/readback failed |
| `NRedDPRecoveryPowerBefore` / `PowerAfter` | Latest observed raw power bytes |
| `NRedDPRecoveryEntered` / `Completed` | PHY-call counts; completion means return, not successful training |
| `NRedDPBiosGuardReady` | 1 only after all additional guards and routes succeed |
| `NRedDPBiosGuardEntered` / `Completed` | Counts of guarded BIOS command calls and returns |
| `NRedDPBiosGuardState` | 0 no timeout/refusal; 1 timed out and unwound; 2 refused unsafe unwind |
| `NRedDPBiosTimeouts` | Count of completed timeout unwinds |
| `NRedDPBiosPollRegister` / `PollValue` | Last actual dword register index and returned value before timeout |
| `NRedDPBiosTableOffset` / `InstructionOffset` | Table offset from BIOS base, instruction offset within that table |
| `NRedDPBiosCompareSource` / `CompareDestination` | Native comparison operands at timeout |
| `NRedDPBiosImage` | Read-only copy of loaded BIOS bytes for offline analysis |

Kernel `DPFix` messages identify installation and the power/readback result before PHY enable.
First verify the expected 0.9.4 UUID, runtime boot argument and both Ready properties equal 1. Test the monitor power
button off/on at 60 Hz while the computer stays awake. Then test macOS system sleep/wake
separately. Repeat at the intended 144 Hz after initial success. A successful single power
cycle does not establish that either other scenario or repeated cycles work. Preserve GPU
reset events to assess whether recovery also works following a compute-queue reset.

If State=1 before the failing enable, the retained-D3 hypothesis is unsupported for that
attempt. If State=2 but the same hang follows, receiver wake is insufficient. The next code
investigation is the transmitter command's exact register/condition and safe BIOS error unwind,
not stronger unbounded AUX retries or fabricated success.

AMD's reference definitions are in Linux
[atombios.h](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/include/atombios.h)
and the [display BIOS command implementation](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/display/dc/bios/command_table.c).
The [Linux ATOM interpreter](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/amdgpu/atom.c)
has loop-abort handling; a watchdog alone would not establish correct DP output here.
