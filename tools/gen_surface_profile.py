"""Generate an exact, signed-file-verified 24H232 surface reference; no runtime writes.
Adapted from steve12311/NootedRed 31fcc872807ae06f59d99016dd5ef80d8996e8ec.
"""
import argparse
import hashlib
import json
import struct
import subprocess
from pathlib import Path

from surface_profile.reader import CacheReader, array, macho
from surface_profile.resolver import ResolverData
from surface_profile.scratch import generate, supported_devices, SYMBOL

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'build/steve-surface-24H232-20261028/generation'
OUTPUT = ROOT / 'NootedRed/UserSurface24H232Data.hpp'
INIT = '__Z29amdMtl_HWL_InitDeviceSettingsP18AMD_DeviceSettingsP18AMDCommonHwInfoRec'
OVERRIDE = '__Z33amdMtl_HWL_OverrideDeviceSettingsP18AMD_DeviceSettingsP18AMDCommonHwInfoRec'
SETTINGS = '__Z29amdMtl_OverrideDeviceSettingsP18AMD_DeviceSettings'
CONSTRUCTOR = '-[GFX9_MtlRenderPipelineState initWithDevice:pipelineStateDescriptor:vertexVariant:fragmentVariant:]'
SUBMIT = '-[GFX9AMD_MtlCmdQueue submitCommandBuffers:count:]'



def verify_signed_spans(cache,spans):
    checked=set()
    for address,length in spans:
        for page in range(address&~4095,(address+length+4095)&~4095,4096):
            if page in checked:continue
            checked.add(page)
            mapping=next((m for m in cache.mappings if m[0]<=page and page+4096<=m[1]),None)
            if not mapping:raise ValueError('Reference page crosses cache mapping')
            start,_,offset,h=mapping;position=offset+page-start
            h.seek(40);sigoff,sigsize=struct.unpack('<QQ',h.read(16));h.seek(sigoff);blob=h.read(sigsize)
            if struct.unpack_from('>I',blob)[0]!=0xfade0cc0:raise ValueError('Missing embedded signature container')
            verified=0
            for i in range(struct.unpack_from('>I',blob,8)[0]):
                _,cdpos=struct.unpack_from('>II',blob,12+8*i)
                if struct.unpack_from('>I',blob,cdpos)[0]!=0xfade0c02:continue
                cd=blob[cdpos:];hashoff,_,_,count,limit=struct.unpack_from('>5I',cd,16)
                size,typ,_,power=struct.unpack_from('4B',cd,36)
                if power!=12 or position%4096 or position+4096>limit or position//4096>=count:raise ValueError('CodeDirectory page bounds')
                expected=cd[hashoff+position//4096*size:hashoff+(position//4096+1)*size]
                actual=hashlib.new({1:'sha1',2:'sha256',3:'sha256',4:'sha384'}[typ],cache.read(page,4096)).digest()[:size]
                if actual!=expected:raise ValueError(f'Reference page hash mismatch at {page:#x}')
                verified+=1
            if not verified:raise ValueError('No CodeDirectory page evidence')
    print('Verified',len(checked),'full file pages against embedded CodeDirectory hashes (not CMS trust)')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=Path('/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld'))
    parser.add_argument('--check',action='store_true')
    args = parser.parse_args()
    profile = json.loads((ROOT / 'tools/fixtures/surface-24H232.json').read_text())
    WORK.mkdir(parents=True, exist_ok=True)
    cache = CacheReader(args.cache, profile['cache_uuid'])
    try:
        if cache.base != profile['base'] or cache.image_base != profile['image_base']:
            raise ValueError('Pinned cache/image base mismatch')
        functions = {}
        for name, meta in profile['metal'].items():
            address, code = cache.function(name)
            if address != meta['address'] or len(code) != meta['size'] or hashlib.sha256(code).hexdigest() != meta['sha256']:
                raise ValueError(f'Sequoia 原生函数未核实：{name}')
            functions[name] = address, code
        verify_signed_spans(cache,[(a,len(b)) for a,b in functions.values()])
        resolver = ResolverData(cache, WORK)
        ctor, ctor_native = functions[CONSTRUCTOR]
        # Verify the moved ObjC slot independently by section and class-symbol identity.
        super_slot=ctor+53+4+struct.unpack_from('<i',ctor_native,53)[0]
        owners=[s for s in cache.sections if s[0]=='__objc_superrefs' and s[1]<=super_slot and super_slot+8<=s[1]+s[2]]
        expected_class=next(a for a,n in cache.symbols if n=='_OBJC_CLASS_$_GFX9_MtlRenderPipelineState')
        if len(owners)!=1 or resolver.pointer(super_slot)!=expected_class:
            raise ValueError('Constructor superclass reference identity mismatch')
        init, native = functions[INIT]
        refs = resolver.references(native, init, 'init')
        if [r[0] for r in refs] != [135, 197, 211] or any(r[3] for r in refs):
            raise ValueError('初始化外部引用布局变化')
        targets = [resolver.images[i][1] + rva for _, i, rva, _ in refs]
        if targets[1] != functions[SETTINGS][0] or cache.read(targets[0], 4) != struct.pack('<f', 3.0):
            raise ValueError('初始化目标或常量未核实')
        dump=cache.read(targets[2],6)
        if dump!=bytes.fromhex('554889e55dc3') or not any(a==targets[2] and n=='__Z25amdMtl_DumpSettingsValuesP18AMD_DeviceSettings' for a,n in cache.symbols):
            raise ValueError('Native settings dump stub identity mismatch')
        verify_signed_spans(cache,[(targets[0],4),(targets[2],6),(super_slot,8)])
        assembly = (ROOT / 'tools/fixtures/surface_srd_init.s').read_text()
        for old, new in zip([0x7ffb10fbfde8, 0x7ffb10c5422b, 0x7ffb10c545c6, 0x7ffb10d71a28],
                            [*targets, init]):
            assembly = assembly.replace(hex(old), hex(new))
        source, obj = WORK / 'init.s', WORK / 'init.o'
        source.write_text(assembly)
        subprocess.run(['clang', '-c', str(source), '-o', str(obj)], check=True, timeout=60)
        data = obj.read_bytes()
        _, sections, _ = macho(lambda a, n: data[a:a+n], 0)
        section = next(s for s in sections if s[0] == '__text')
        payload = data[section[3]:section[3]+section[2]]
        if len(payload) != len(native):
            raise ValueError('SRD 载荷越界')
        override, override_native = functions[OVERRIDE]
        override_payload = b'\xe9' + struct.pack('<i', init + 166 - override - 5) + b'\x90'*5
        gate = profile['legacy_blend_gate']
        if cache.read(gate, 2) != b'\x75\x0b':
            raise ValueError('LegacyBlend 能力 gate 未核实')
        # 短覆盖入口连同下一完整函数核验；补丁仍仅改入口本身。
        end = min(a for a, _ in cache.symbols if a > override + len(override_native))
        override_context = cache.read(override, end-override)
        if len(override_context)!=profile['override_context']['size'] or hashlib.sha256(override_context).hexdigest() != profile['override_context']['sha256']:
            raise ValueError('覆盖入口的完整上下文变化')
        verify_signed_spans(cache,[(override,len(override_context))])
        records = [(init, native, payload), (override, override_native, override_payload),
                   (gate, b'\x75\x0b', b'\xeb\x0b')]
        scratch = generate(cache, profile=profile['metal'][SYMBOL])
        records.append((scratch['address'], bytes.fromhex(scratch['original']), bytes.fromhex(scratch['patched'])))
        ctor, ctor_native = functions[CONSTRUCTOR]
        ctor_patched = bytearray(ctor_native)
        ctor_patched[gate-ctor:gate-ctor+2] = b'\xeb\x0b'
        resolver.add(init, native, payload)
        resolver.add(override, override_context, override_payload + override_context[10:])
        resolver.add(ctor, ctor_native, bytes(ctor_patched))
        resolver.add(records[3][0], records[3][1], records[3][2])
        resolver.add(*functions[SETTINGS], functions[SETTINGS][1])
        locations = [(0, 0), (1, 0), (2, gate-ctor), (3, 0)]
        header = ('// Generated by tools/gen_surface_profile.py; exact 24H232 file references. No runtime owner enabled.\n#pragma once\n'
                  '#include <UserVideoGuardTypes.hpp>\n#include <UserCacheResolver.hpp>\nnamespace UserSurface24H232Data {\n'
                  'using Patch = UserVideoGuardTypes::Patch;\n')
        header += array('CacheUUID', cache.uuid)
        header += array('NativeDump',dump)
        header += f'inline constexpr UInt64 CacheBase = 0x{cache.base:X}ULL;\n'
        header += 'inline constexpr UInt32 MaxPatchSize = 456;\n'
        for i, (_, original, patched) in enumerate(records):
            header += array(f'Original{i}', original) + array(f'Patched{i}', patched)
        device_records = []
        for device in supported_devices():
            name = f'Patches{device:04X}'
            variant = payload.replace(bytes.fromhex('817e0c38160000'), bytes.fromhex('817e0c') + struct.pack('<I', device))
            patched_scratch = bytes.fromhex(generate(cache, device, profile['metal'][SYMBOL])['patched'])
            variants = [variant, override_payload, b'\xeb\x0b', patched_scratch]
            device_records.append({'device_id': device, 'records': [
                {'label': label, 'address': a, 'original': o.hex(), 'patched': p.hex()}
                for label, (a, o, _), p in zip(['init', 'override', 'blend', 'scratch'], records, variants)]})
            header += array(f'Init{device:04X}', variant) + array(f'Scratch{device:04X}', patched_scratch)
            header += f'inline constexpr Patch {name}[] = {{\n'
            for i, (address, original, _) in enumerate(records):
                replacement = f'Init{device:04X}' if i == 0 else f'Scratch{device:04X}' if i == 3 else f'Patched{i}'
                header += f'    {{0x{address-cache.base:X}ULL, Original{i}, {replacement}, {len(original)}}},\n'
            header += '};\n'
        header += ('struct DevicePatchSet { UInt32 deviceID; const Patch* patches; };\n'
                   'inline constexpr DevicePatchSet DevicePatches[] = {\n')
        for device in supported_devices():
            header += f'    {{0x{device:04X}, Patches{device:04X}}},\n'
        header += ('};\ninline const Patch* findDevice(UInt32 deviceID) {\n'
                   '    for (const auto& e : DevicePatches) { if (e.deviceID == deviceID) { return e.patches; } }\n'
                   '    return nullptr;\n}\n')
        header += resolver.header(locations)
        submit, submit_code = functions[SUBMIT]
        submit_resolver = ResolverData(cache, WORK)
        submit_resolver.add(submit, submit_code, submit_code)
        header += 'namespace Submit {\n' + submit_resolver.header([]) + '}\n}\n'
        if args.check:
            if OUTPUT.read_text()!=header:raise ValueError('Generated profile differs from committed header')
        else:OUTPUT.write_text(header)
        report = {'super_slot':super_slot,'super_slot_class':expected_class,'records': [{'address': a, 'original': o.hex(), 'patched': p.hex()} for a, o, p in records],
                  'device_records': device_records, 'targets': targets, 'submit': submit, 'cacheUUID': cache.uuid.hex()}
        (WORK / 'patch-data.json').write_text(json.dumps(report, indent=2)+'\n')
        print('Verified' if args.check else 'Generated','24H232 surface reference:',len(header),'bytes; no runtime patches installed')
    finally:
        cache.close()


if __name__ == '__main__':
    main()
