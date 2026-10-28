# HP 872E ACPI review — 27 October 2026

Recommendation: keep all five current AMLs. No additional AML or functional
refactor is justified by the current hardware evidence. No EFI file, patch,
quirk or ACPI load order was changed in this review.

## Installed tables

| File | Actual role on this machine | Decision |
|---|---|---|
| SSDT-EC.aml | Disables native EC0 for Darwin, delegates to renamed XSTA for other OSes, and provides Darwin-only fake EC with ACID0001. Depends on the EC _STA rename. Live fake EC has _STA 15. | Keep as a coupled table/rename pair. |
| SSDT-PLUG-ALT.aml | Provides legacy Processor objects C000–C00F and plugin-type on the first object. Firmware instead declares ACPI0007 Device objects under _SB.PLTF. The added objects are under _SB, so the same short names have different full paths. This matches 16 logical CPUs; live C000 has plugin-type=1. | Keep. Do not remove because the template name suggests Intel. No claim that Intel XCPM or CPUFriend provides AMD power management. |
| SSDT-USB-Reset.aml | Hides the three firmware RHUB objects under PT00, XHC0 and XHC2 on Darwin. XHC2 depends on the scoped firmware XHC1 rename. This is separate from the USB port map. | Keep; current three xHCI controllers/USBMap and physical wake/device checks work. |
| SSDT-USBX.aml | Darwin-only USB power properties: sleep/wake supply 5100 and port-current limit 2100. Live USBX exposes the same values. | Keep. No evidence supports raising these values. |
| SSDT-GPE0-MUX.aml | Recreates serialized _GPE._L00 and calls both firmware handlers renamed XH00 and XG00. | Keep together with both narrowly targeted renames. |

The directory has exactly five AML files, all referenced and enabled. There
are no unused AML files to delete. Every table header length matches its file
length, each checksum sums to zero, and all five disassemble successfully.

## Firmware patch and drop checks

Against the supplied SysReport firmware (HP S27 02.23.00, 24 July 2026):

- EC rename `03 14 09 _STA` matches once in DSDT, offset 47970.
- XHC1→XHC2 matches once in the HP 872E 57445-byte DSDT, offset 45075.
- DSDT _L00→XH00 matches once, offset 54840.
- Artic/14858-byte ssdt7 _L00→XG00 matches once, offset 14017.
- The Artic/5132-byte SSDT deletion selects only ssdt9, the previously identified
  inactive test fixture referencing nonexistent I2CD.

A patched offline namespace was built from the firmware copies, applied
renames, selected drop and five added AMLs. Each added table and DSDT disassemble
with the other tables as external namespace context, without reported errors.
The older iasl 20200925 multi-input -da invocation repeated external namespace
loads and reported PTOS duplicates; single-table external-context checks
succeed. This tool output was not treated as a new runtime firmware error and
no firmware table was dropped to hide it. Static namespace checks do not
execute methods, validate hardware register behaviour or guarantee future boots.

The retained firmware reference is not a fresh post-update firmware extraction.
Recheck all lengths, IDs, CPU counts and byte matches after a BIOS update.
Absence of matching ACPI errors in a retained log does not prove an entirely
clean boot. Existing same-boot physical sleep/wake, USB, speaker, Wi-Fi and
Bluetooth checks provide the functional evidence available here.

## Refactoring worth doing later

1. Keep source ASL, compile instructions, compiler version, output hashes and
   machine/BIOS selectors together in version control. The disassembled sources
   and hashes are already saved under build/acpi-review-20261027 for this audit.
   Do not replace the known-working AML with newly compiled output merely to
   normalize compiler dates or table headers.
2. Clarify config comments: the GPE entry still says isolated test although its
   operation has been physically tested. CPU-table comments should explain legacy
   processor enumeration instead of implying generic Ryzen frequency optimization.
3. Keep EC and USBX separate for independent rollback. Merging them saves only a
   small table header and has no demonstrated boot/runtime performance benefit.
4. Do not reintroduce the EC-scoping change from the withdrawn 23 October batch.
   That batch failed before macOS, and the individual cause was never isolated.
   The broad current EC selector matches once on this firmware; narrowing it is
   an optional isolated future change, not a proven fix required now.

No reason was found to add generic HPET, AWAC/RTC, PMC, SMBus, CPUFriend/PLUG,
CPUR or PNLF tables. Such additions require a specific missing function or
firmware defect. CPU compatibility objects already exist, native RTC is present,
and the system has a desktop display rather than an internal backlight. Do not
inject the generated pcidevices.dsl just to add names/model labels.

A future functional change should be isolated and boot-tested with recovery EFI
available, preserving the coupled GPE and USB renames. This audit leaves the
pending production logging configuration intact.

Evidence: build/acpi-review-20261027/SUMMARY.json, the five source disassemblies,
per-table namespace logs and patched firmware copies.

Primary references:
- https://dortania.github.io/OpenCore-Install-Guide/AMD/zen.html#acpi
- https://github.com/acidanthera/OpenCorePkg/blob/master/Docs/AcpiSamples/Source/SSDT-PLUG-ALT.dsl
- https://dortania.github.io/Getting-Started-With-ACPI/Universal/ec-methods/manual.html
