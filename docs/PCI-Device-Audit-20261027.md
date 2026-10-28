# PCI device verification — 27 October 2026

All **36 exported PCI functions match 36 live PCI functions** by bus/device/function and vendor/device ID. No exported device is missing or has a changed ID. This is detection verification, not a claim that every optional function is operational.

The JSON and text each list all 36 functions. The plist contains 36 matching DeviceProperties paths; the DSL is generated property-injection source, rather than an additional hardware probe. None of these exports was installed into EFI. The files were exported at 13:18, before the working DW1560 Wi-Fi setup; live attachment is therefore more informative than the old BundleID column.

## Functional findings

| Device | Evidence and result |
|---|---|
| AMD Renoir iGPU `1002:1636` | X5000 accelerator/X6000 framebuffer stack attached; Metal 3 reported, 1.5 GB VRAM, current display 2560×1440 at 144 Hz. Desktop and wake were user-verified earlier this same boot. This audit did not submit new GPU stress/video workloads. |
| Solidigm P41 Plus NVMe `025e:f1ab` | IONVMe controller and block-storage stack attached; disk0 is the active system disk. SMART Verified, TRIM Yes, reported link 8.0 GT/s ×4. No write benchmark or destructive disk test was performed. |
| USB `1022:43ef`, two `1022:1639` | All three xHCI controllers attach AppleUSBXHCIPCI and expose mapped ports. Connected USB devices enumerate. User confirmed usual USB ports after real system wake; every individual connector/speed/USB-C orientation has not been re-tested here. |
| HD Audio `1022:15e3` | AppleHDA controller/codec stack attached; default output is Internal Speakers. User confirmed speaker playback and post-wake operation. Microphone recording and jack switching remain physical tests. |
| Display audio `1002:1637` | AppleGFXHDA controller and display-audio engine exist; MG27S9Q is listed as an audio output. Audible playback over the display connection has not been tested. |
| DW1560 Wi-Fi `14e4:43b1` | AirPort_BrcmNIC now attaches under ARPT. This boot has verified Wi-Fi-bound HTTPS connectivity and automatic reconnection after system sleep. Prior export only showed generic IOPCIFamily. |
| Realtek Ethernet `10ec:8168` | RealtekRTL8111 and en0 exist. Current physical link is inactive; wired DHCP/traffic cannot be marked verified. |
| SATA `1022:43eb` | CtlnaAHCIPort controller and ports present; System Profiler lists no SATA drives. Disk read/write functionality remains untested without an attached SATA drive. |
| AMD IOMMU `1022:1631`, PSP `1022:15df`, SMBus `1022:790b` | Enumerated. No dedicated active functional child driver was observed in the PCI snapshot. This does not prove IOMMU/DMA remapping, PSP security features or SMBus sensor access works in macOS. |
| Realtek management `10ec:816e/816a/816d/816c` | Enumerated. RTL8111 service objects appear, often state 0; their names do not verify BMC/IPMI/UART or the management USB function. These are not four additional ordinary Ethernet/USB ports. |
| Host bridges, PCIe bridges, LPC and CPU fabric functions | Enumerated; PCIe bridge driver descendants are present where applicable. No missing function was found; lack of a separate user-facing driver on a host/fabric node is not by itself an error. |

Bluetooth is USB rather than a PCI function. BCM20702 `0a5c:216f` is detected, and the preceding sleep/wake capture and user confirmation verified keyboard/phone connectivity.

## Interpretation of export fields

- BundleID values can refer to a generic controller/provider or a service object that is not functional. The Realtek management rows illustrate why this field alone cannot certify a device.
- The `???` name for chipset USB `1022:43ef` is an identification-database label gap; its live AppleUSBXHCIPCI driver and ports are present.
- All exported ASPM fields read Disabled. This is not proof of a device failure, and this audit did not enable ASPM globally.
- Generated paths use PciRoot(0x1), and live PCI0 exposes _UID 1. Do not blindly merge the generated plist/DSL into an existing EFI or rewrite working device properties: path resolution and each intended property need separate checks.

## Complete inventory

| BDF | Vendor:device | Function | Live name | Detection |
|---|---|---|---|---|
| 00:00.0 | `1022:1630` | Renoir/Cezanne Root Complex | pci1022,1630 | Matched |
| 00:00.2 | `1022:1631` | Renoir/Cezanne IOMMU | pci1022,1631 | Matched |
| 00:01.0 | `1022:1632` | Renoir PCIe Dummy Host Bridge | pci1022,1632 | Matched |
| 00:02.0 | `1022:1632` | Renoir PCIe Dummy Host Bridge | pci1022,1632 | Matched |
| 00:02.1 | `1022:1634` | Renoir/Cezanne PCIe GPP Bridge | GPP1 | Matched |
| 00:02.2 | `1022:1634` | Renoir/Cezanne PCIe GPP Bridge | GPP2 | Matched |
| 00:08.0 | `1022:1632` | Renoir PCIe Dummy Host Bridge | pci1022,1632 | Matched |
| 00:08.1 | `1022:1635` | Renoir Internal PCIe GPP Bridge to Bus | GP17 | Matched |
| 00:14.0 | `1022:790b` | FCH SMBus Controller | SMBS | Matched |
| 00:14.3 | `1022:790e` | FCH LPC Bridge | LPCB | Matched |
| 00:18.0 | `1022:1448` | Renoir Device 24: Function 0 | pci1022,1448 | Matched |
| 00:18.1 | `1022:1449` | Renoir Device 24: Function 1 | pci1022,1449 | Matched |
| 00:18.2 | `1022:144a` | Renoir Device 24: Function 2 | pci1022,144a | Matched |
| 00:18.3 | `1022:144b` | Renoir Device 24: Function 3 | pci1022,144b | Matched |
| 00:18.4 | `1022:144c` | Renoir Device 24: Function 4 | pci1022,144c | Matched |
| 00:18.5 | `1022:144d` | Renoir Device 24: Function 5 | pci1022,144d | Matched |
| 00:18.6 | `1022:144e` | Renoir Device 24: Function 6 | pci1022,144e | Matched |
| 00:18.7 | `1022:144f` | Renoir Device 24: Function 7 | pci1022,144f | Matched |
| 01:00.0 | `1022:43ef` | ??? | PT00 | Matched |
| 01:00.1 | `1022:43eb` | 500 Series Chipset SATA Controller | PT01 | Matched |
| 01:00.2 | `1022:43e9` | 500 Series Chipset Switch Upstream Port | PT02 | Matched |
| 06:00.0 | `1002:1636` | Renoir [Radeon Vega Series / Radeon Vega Mobile Series] | IGPU | Matched |
| 06:00.1 | `1002:1637` | Renoir/Cezanne HDMI/DP Audio Controller | HDAU | Matched |
| 06:00.2 | `1022:15df` | Raven/Raven2/FireFlight/Renoir/Cezanne Platform Security Processor | PSP | Matched |
| 06:00.3 | `1022:1639` | Renoir/Cezanne USB 3.1 | XHC0 | Matched |
| 06:00.4 | `1022:1639` | Renoir/Cezanne USB 3.1 | XHC2 | Matched |
| 06:00.6 | `1022:15e3` | Ryzen HD Audio Controller | HDEF | Matched |
| 05:00.0 | `025e:f1ab` | P41 Plus NVMe SSD (DRAM-less) [Echo Harbor] | pci25e,f1ab | Matched |
| 02:08.0 | `1022:43ea` | 500 Series Chipset Switch Downstream Port | PT28 | Matched |
| 02:09.0 | `1022:43ea` | 500 Series Chipset Switch Downstream Port | pci-bridge | Matched |
| 04:00.0 | `10ec:816e` | RealManage BMC | pci10ec,816e | Matched |
| 04:00.1 | `10ec:8168` | RTL8111/8168/8211/8411 PCI Express Gigabit Ethernet Controller | ethernet | Matched |
| 04:00.2 | `10ec:816a` | RTL8111xP UART #1 | pci10ec,816a | Matched |
| 04:00.4 | `10ec:816d` | RTL811x EHCI host controller | pci10ec,816d | Matched |
| 04:00.7 | `10ec:816c` | RTL8111xP IPMI interface | pci10ec,816c | Matched |
| 03:00.0 | `14e4:43b1` | BCM4352 802.11ac Dual Band Wireless Network Adapter | ARPT | Matched |

Evidence: `build/pci-audit-20261027/`, including the source exports, live IORegistry, driver descendants, System Profiler reports and SHA-256 hashes. No EFI, ACPI, kext, boot argument or system setting was changed by this audit.

## Unused USB kext cleanup

At the user's request, removed disabled USBToolBox.kext and UTBDefault.kext
and their two disabled Kernel/Add entries from the active internal EFI.
USBMap.kext remains enabled and byte-identical; its personalities use Apple's
AppleUSBHostMergeProperties and declare no USBToolBox dependency. All remaining
enabled kext dependencies and paths were checked. The running kernel did not
list USBToolBox. OpenCore 1.0.9 validation passed, with all other EFI files and
configuration values verified unchanged. Both removed entries were already
disabled on the working sleep/wake boot, so no immediate reboot is required.

Backup: /Users/tvtuan/EFI-Backups/INTERNAL-before-unused-USB-kext-cleanup-20261027-140254/EFI
Evidence: build/usb-kext-cleanup-20261027/CLEANUP.json.
The EFI volume was already mounted and was left mounted.
