#!/usr/bin/env python3
"""Capture one explicitly selected zero-frame HEVC lifecycle experiment.

Does not modify EFI or start Zalo. A timeout cannot contain a GPU/kernel hang.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from run_hevc_isolation import EXPECTED_UUID, GPU_PREDICATE, gpu_events

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / 'build/zalo-freeze-20261026/lifecycle'


def command(argv, timeout=10):
    return subprocess.run(argv, capture_output=True, timeout=timeout)


def save(path, data):
    with path.open('wb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def record(path, value):
    save(path, (json.dumps(value, indent=2) + '\n').encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=['normal', 'small', 'pair'], required=True)
    parser.add_argument('--hardware', action='store_true', required=True)
    parser.add_argument('--yes', action='store_true', required=True)
    parser.add_argument('--invalidate', action='store_true')
    parser.add_argument('--expected-uuid', default=EXPECTED_UUID,
                        help='explicitly reviewed loaded-driver UUID for this experiment')
    args = parser.parse_args()
    binary, fixtures = STUDY / 'vt_lifecycle_probe', STUDY / 'fixtures.json'
    loaded = command(['/usr/sbin/kextstat', '-l', '-b', 'org.ChefKiss.NootedRed'])
    if loaded.returncode or args.expected_uuid.upper().encode() not in loaded.stdout:
        parser.error('loaded driver does not match the baseline; review identity before testing')
    before = gpu_events()
    if before:
        parser.error('GPU failure events already exist on this boot; no workload submitted')
    ring = command(['sudo', '-n', '/sbin/dmesg'])
    if ring.returncode:
        parser.error('sudo -v is required for kernel capture')
    check = command([str(binary), str(fixtures)])
    if check.returncode:
        parser.error('format-only probe failed')
    out = STUDY / f'capture-{dt.datetime.now():%Y%m%d-%H%M%S}-{args.case}'
    out.mkdir(mode=0o700)
    probe = [str(binary), str(fixtures), '--case', args.case, '--hardware', '--yes']
    if args.invalidate:
        probe.append('--invalidate')
    record(out / 'REQUEST.json', {
        'started_at': dt.datetime.now().astimezone().isoformat(),
        'boot_uuid': command(['sysctl', '-n', 'kern.bootsessionuuid']).stdout.decode().strip(),
        'boot_args': command(['sysctl', '-n', 'kern.bootargs']).stdout.decode().strip(),
        'command': probe,
        'sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in [binary, fixtures, ROOT/'tools/vt_lifecycle_probe.mm']},
        'note': 'Hardware session creation/release may freeze the PC even with zero decoded frames.'})
    save(out / 'loaded-kext.txt', loaded.stdout + loaded.stderr)
    record(out / 'before-GPU-events.json', before)
    save(out / 'dmesg-before.txt', ring.stdout)
    save(out / 'ioreg-before.txt', command(['ioreg', '-lw0', '-r', '-n', 'IGPU']).stdout)
    print(f'Capturing hardware lifecycle to {out}', flush=True)
    predicate = f'({GPU_PREDICATE}) OR process == "VTDecoderXPCService" OR (process == "kernel" AND (eventMessage CONTAINS[c] "VCN" OR eventMessage CONTAINS[c] "NootedRed"))'
    live = (out / 'live-system.ndjson').open('wb', buffering=0)
    stream = subprocess.Popen(['/usr/bin/log', 'stream', '--style', 'ndjson', '--level', 'info',
                               '--predicate', predicate], stdout=live, stderr=subprocess.STDOUT)
    stdout = (out / 'probe.jsonl').open('wb', buffering=0)
    stderr = (out / 'probe.stderr').open('wb', buffering=0)
    process = None
    stop = None
    count = 0
    last = None
    ended = None
    started = time.monotonic()
    try:
        while True:
            if stream.poll() is not None:
                stop = 'live log capture exited'; break
            ring = command(['sudo', '-n', '/sbin/dmesg'], timeout=5)
            if ring.returncode:
                stop = 'kernel ring capture failed'; break
            digest = hashlib.sha256(ring.stdout).digest()
            if digest != last:
                save(out / f'dmesg-{count:04d}.txt', ring.stdout)
                count += 1
                last = digest
            # Read the ring before creating the decoder, then retain early fault evidence.
            if process is None:
                process = subprocess.Popen(probe, stdout=stdout, stderr=stderr)
                record(out / 'PROCESS.json', {'pid': process.pid})
            if process.poll() is not None and ended is None:
                ended = time.monotonic()
            if ended is not None and time.monotonic() - ended >= 20:
                break
            if ended is None and time.monotonic() - started > 25:
                stop = '25-second probe deadline; GPU may remain hung'; break
            time.sleep(0.2)
    except (subprocess.TimeoutExpired, OSError) as error:
        stop = f'capture error: {error}'
    finally:
        for child in [process, stream]:
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    try:
                        child.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        stop = 'child remained in kernel wait after kill'
        for handle in [stdout, stderr, live]:
            os.fsync(handle.fileno())
            handle.close()
    after = gpu_events()
    record(out / 'after-GPU-events.json', after)
    save(out / 'ioreg-after.txt', command(['ioreg', '-lw0', '-r', '-n', 'IGPU']).stdout)
    phases = []
    for line in (out/'probe.jsonl').read_text().splitlines():
        try:
            phases.append(json.loads(line))
        except ValueError:
            pass
    summary = {
        'ended_at': dt.datetime.now().astimezone().isoformat(),
        'returncode': process.returncode if process else None,
        'stopped_reason': stop, 'kernel_snapshots': count,
        'new_GPU_failure_events': len(after) - len(before),
        'last_phase': phases[-1] if phases else None,
        'hardware_selections': [p for p in phases if p.get('phase') == 'selection'],
        'lifecycle_completed': bool(phases and phases[-1].get('phase') == 'complete'),
        'driver_fixed': False}
    record(out / 'SUMMARY.json', summary)
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if not stop and process and process.returncode == 0 and not after else 1


if __name__ == '__main__':
    raise SystemExit(main())
