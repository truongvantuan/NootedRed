#!/usr/bin/env python3
"""Passive App Store incident capture; never opens apps or submits a GPU workload."""
import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from run_hevc_isolation import command, gpu_events, STUDY, EXPECTED_UUID


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seconds', type=int, default=120)
    args = ap.parse_args()
    if not 30 <= args.seconds <= 300:
        ap.error('duration must be 30–300 seconds')
    if command(['sudo','-n','/sbin/dmesg']).returncode:
        ap.error('run sudo -v first')
    loaded = command(['/usr/sbin/kextstat','-l','-b','org.ChefKiss.NootedRed'])
    if loaded.returncode or EXPECTED_UUID not in loaded.stdout.decode():
        ap.error('loaded kext differs from the isolation baseline')
    out = STUDY/f'appstore-home-{dt.datetime.now():%Y%m%d-%H%M%S}'
    out.mkdir(mode=0o700)
    before = gpu_events()
    (out/'GPU-before.json').write_text(json.dumps(before,indent=2)+'\n')
    (out/'loaded-kext.txt').write_bytes(loaded.stdout+loaded.stderr)
    for name, key in [('boot-args','kern.bootargs'),('boot-uuid','kern.bootsessionuuid')]:
        (out/f'{name}.txt').write_bytes(command(['sysctl','-n',key]).stdout)
    request = {'started_at':dt.datetime.now().astimezone().isoformat(),'duration_seconds':args.seconds,
               'GPU_work_submitted_by_collector':False,'apps_launched_by_collector':False,
               'capture_scope':'App Store/decoder unified log and filesystem reads, kernel ring',
               'note':'Capture adds timing overhead. A system freeze may prevent completion; snapshots are flushed individually.'}
    (out/'REQUEST.json').write_text(json.dumps(request,indent=2)+'\n')
    children = []
    handles = []
    predicates = '(process == "kernel" AND (eventMessage CONTAINS[c] "GPU" OR eventMessage CONTAINS[c] "VCN" OR eventMessage CONTAINS[c] "channel timeout")) OR process == "App Store" OR process == "VTDecoderXPCService"'
    for filename, argv in [
        ('live-system.ndjson',['/usr/bin/log','stream','--style','ndjson','--level','debug','--predicate',predicates]),
        ('filesystem.txt',['sudo','-n','/usr/bin/fs_usage','-w','-f','filesys','-t',str(args.seconds),'App Store','VTDecoderXPCService'])]:
        handle = (out/filename).open('wb');handles.append(handle)
        children.append(subprocess.Popen(argv,stdout=handle,stderr=subprocess.STDOUT))
    print(f'Capture armed for {args.seconds} seconds: {out}',flush=True)
    start = time.monotonic();last = None;saved = 0;errors = []
    try:
        while time.monotonic()-start < args.seconds:
            ring = command(['sudo','-n','/sbin/dmesg'],timeout=5)
            if ring.returncode:
                errors.append('kernel ring read failed');break
            digest = hashlib.sha256(ring.stdout).digest()
            if digest != last:
                with (out/f'dmesg-{saved:03d}.txt').open('wb') as handle:
                    handle.write(ring.stdout);handle.flush();os.fsync(handle.fileno())
                saved += 1;last = digest
            time.sleep(0.5)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=2)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=2)
        for handle in handles:handle.close()
    after = gpu_events()
    (out/'GPU-after.json').write_text(json.dumps(after,indent=2)+'\n')
    result = {'ended_at':dt.datetime.now().astimezone().isoformat(),'kernel_snapshots':saved,
              'GPU_failure_events_before':len(before),'GPU_failure_events_after':len(after),
              'new_GPU_failure_events':max(0,len(after)-len(before)),'capture_errors':errors,
              'GPU_work_submitted_by_collector':False,'apps_launched_by_collector':False,
              'capture_child_exit_codes':[p.returncode for p in children]}
    (out/'SUMMARY.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2),flush=True)


if __name__ == '__main__':
    main()
