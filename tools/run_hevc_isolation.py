#!/usr/bin/env python3
"""Capture one explicit HEVC/HEIF experiment. Never changes EFI or reboots.

A child-process timeout cannot contain a GPU/kernel hang. Hardware runs require
--hardware --yes, a full-VDA boot, the pinned loaded kext and a clean GPU log.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT/'build/hevc-root-cause-20261026'
EXPECTED_UUID = '3119DE95-4690-35E6-86A8-869A8ADFC3B7'
GPU_PREDICATE = ('process == "kernel" AND (eventMessage CONTAINS[c] "GPURestartBegin" '
                 'OR eventMessage CONTAINS[c] "GPU Hang" OR eventMessage CONTAINS[c] "channel timeout" '
                 'OR (senderImagePath CONTAINS[c] "AMDRadeon" '
                 'AND (eventMessage CONTAINS[c] "event timeout" OR eventMessage CONTAINS[c] "is hung!")))')


def command(args, timeout=30):
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)


def gpu_events(timeout=120):
    boot = command(['sysctl','-n','kern.boottime']).stdout.decode()
    match = re.search(r'sec = (\d+)', boot)
    if not match:
        raise RuntimeError('cannot establish current boot time')
    start = dt.datetime.fromtimestamp(int(match[1])).strftime('%Y-%m-%d %H:%M:%S')
    result = command(['/usr/bin/log','show','--start',start,'--style','ndjson','--predicate',GPU_PREDICATE], timeout=timeout)
    if result.returncode:
        raise RuntimeError('GPU log query failed')
    uuid = command(['sysctl','-n','kern.bootsessionuuid']).stdout.decode().strip().upper()
    rows = []
    for line in result.stdout.decode(errors='replace').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get('bootUUID','').upper() == uuid and row.get('eventMessage'):
            rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--api', choices=['vt','imageio'], required=True)
    ap.add_argument('--case', choices=['icon-colour','icon-alpha','banner-colour','banner-alpha','icon-combined','banner-combined','grid-tile','grid-combined'], required=True)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--software', action='store_true')
    mode.add_argument('--hardware', action='store_true')
    ap.add_argument('--yes', action='store_true')
    ap.add_argument('--imageio-software', action='store_true')
    args = ap.parse_args()
    if args.api == 'vt' and args.case.endswith('combined'):
        ap.error('combined image requires ImageIO; VT tests exactly one extracted item')
    if args.imageio_software and args.api != 'imageio':
        ap.error('ImageIO policy only applies to ImageIO')
    boot = command(['sysctl','-n','kern.bootargs']).stdout.decode().split()
    if args.hardware and (not args.yes or '-NRedVDA' not in boot or any(x in boot for x in ['-NRedAVC','-NRedAVCEncode','-NRedHEVC10'])):
        ap.error('hardware test requires --yes and the prepared full-VDA/Main8 boot')
    loaded = command(['/usr/sbin/kextstat','-l','-b','org.ChefKiss.NootedRed'])
    if loaded.returncode or EXPECTED_UUID not in loaded.stdout.decode():
        ap.error('loaded NootedRed identity does not match the diagnostic baseline')
    if command(['sudo','-n','/sbin/dmesg']).returncode:
        ap.error('run sudo -v first; kernel ring capture is required')
    manifest = json.loads((STUDY/'PROBE-MANIFEST.json').read_text())
    for relative, expected in manifest['sha256'].items():
        if hashlib.sha256((STUDY/relative).read_bytes()).hexdigest() != expected:
            ap.error(f'diagnostic artifact changed: {relative}')
    before = gpu_events()
    if args.hardware and before:
        ap.error('current boot already has GPU failures; no additional hardware work submitted')
    out = STUDY/f'test-{dt.datetime.now():%Y%m%d-%H%M%S}-{args.api}-{args.case}'
    out.mkdir(mode=0o700)
    (out/'before-gpu-events.json').write_text(json.dumps(before,indent=2)+'\n')
    (out/'loaded-kext.txt').write_bytes(loaded.stdout+loaded.stderr)
    (out/'boot-args.txt').write_text(' '.join(boot)+'\n')
    combined = {'icon':'913c798cb17927eeb082a8f08a01fc190e8769985e524f4e8f93537eda800699',
                'banner':'0516dcface41ccf6686b64513593479959a141f32506fc34da4d33bb1dda5d9f',
                'grid':'14244c3eb5f21f0bbdf2f0ea26e5c80873ccdd0c65e9883b84d6a944e3206e15'}
    if args.api == 'vt':
        probe = [str(STUDY/'hevc_item_probe'),str(STUDY/'isolated-items'/f'{args.case}.json'),
                 '--hardware' if args.hardware else '--software']+(['--yes'] if args.hardware else [])
    else:
        path = STUDY/'heif-candidates'/f'{combined[args.case.split("-")[0]]}.heic' if args.case.endswith('combined') else STUDY/'isolated-items'/f'{args.case}.heic'
        probe = [str(STUDY/'heif_image_probe'),str(path),'--decode']+(['--hardware-test','--yes'] if args.hardware else [])
        if args.imageio_software:
            probe += ['--imageio-software']
    request = {'command':probe,'started_at':dt.datetime.now().astimezone().isoformat(),
               'hardware_experiment':args.hardware,'ImageIO_hardware_selection_verified':False,
               'note':'Hardware ImageIO experiment permits hardware but does not prove actual backend selection. VT probe verifies its session separately.'}
    (out/'REQUEST.json').write_text(json.dumps(request,indent=2)+'\n')
    print(f'Capturing one case to {out}', flush=True)
    log_file = (out/'live-system.ndjson').open('wb')
    stream = subprocess.Popen(['/usr/bin/log','stream','--style','ndjson','--level','info','--predicate',
        f'({GPU_PREDICATE}) OR process == "VTDecoderXPCService"'],stdout=log_file,stderr=subprocess.STDOUT)
    output = (out/'probe.jsonl').open('wb')
    errors = (out/'probe.stderr').open('wb')
    process = None
    stop = None
    last = None
    samples = 0
    try:
        started = time.monotonic()
        while True:
            ring = command(['sudo','-n','/sbin/dmesg'],timeout=5)
            if ring.returncode:
                stop = 'kernel capture failed';break
            digest = hashlib.sha256(ring.stdout).digest()
            if digest != last:
                with (out/f'dmesg-{samples:03d}.txt').open('wb') as handle:
                    handle.write(ring.stdout);handle.flush();os.fsync(handle.fileno())
                samples += 1;last = digest
            if process is None:
                process = subprocess.Popen(probe,stdout=output,stderr=errors)
            if process.poll() is not None:
                break
            if time.monotonic()-started > 20:
                stop = '20-second deadline; a process timeout cannot recover a hung GPU';break
            time.sleep(0.5)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)
        stream.terminate()
        try:stream.wait(timeout=2)
        except subprocess.TimeoutExpired:stream.kill();stream.wait(timeout=2)
        output.close();errors.close();log_file.close()
    ring = command(['sudo','-n','/sbin/dmesg'],timeout=5)
    (out/'dmesg-after.txt').write_bytes(ring.stdout)
    after = gpu_events()
    (out/'after-gpu-events.json').write_text(json.dumps(after,indent=2)+'\n')
    result = {'ended_at':dt.datetime.now().astimezone().isoformat(), 'returncode':process.returncode if process else None,
              'stopped_reason':stop,'kernel_ring_snapshots':samples,'GPU_events_before':len(before),'GPU_events_after':len(after),
              'new_GPU_events':max(0,len(after)-len(before)),
              'conclusion':'Review decoder selection, functional output and GPU evidence together. No other workload was submitted.'}
    (out/'SUMMARY.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
