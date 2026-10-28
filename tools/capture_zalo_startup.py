#!/usr/bin/env python3
"""Observe original Zalo with VCN tracing; app launch requires explicit options."""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import time
from pathlib import Path

from run_hevc_isolation import GPU_PREDICATE, gpu_events
from zalo_hevc_guard import processes, plan
from vcn_context_trace import summarize

ROOT = Path(__file__).resolve().parents[1]


def command(argv, timeout=10):
    return subprocess.run(argv, capture_output=True, timeout=timeout)


def save(path, data):
    with path.open('wb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def record(path, value):
    save(path, (json.dumps(value, indent=2) + '\n').encode())


def launch_original_app(app):
    if any(p['browser_main'] or p['GPU_helper'] for p in processes(app)):
        raise RuntimeError('Zalo started before the controlled launch; no second launch requested')
    result = command(['/usr/bin/open', '-a', str(app)])
    if result.returncode:
        raise RuntimeError('LaunchServices could not open original Zalo')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=180)
    parser.add_argument('--expected-uuid', required=True)
    parser.add_argument('--launch-original', action='store_true',
                        help='open original Zalo only after continuous capture starts')
    parser.add_argument('--yes', action='store_true')
    parser.add_argument('--require-vm-trace', action='store_true',
                        help='require the decoder/fault-page VM trace v3 and all five native routes')
    args = parser.parse_args()
    if not 60 <= args.seconds <= 300 or not re.fullmatch(r'[0-9A-Fa-f-]{36}', args.expected_uuid):
        parser.error('capture requires 60–300 seconds and a reviewed driver UUID')
    if args.launch_original and not args.yes:
        parser.error('opening the freeze-prone application requires --launch-original --yes')
    app = Path('/Applications/Zalo.app')
    identity = plan(app)  # Inspect identity; do not use the guarded command.
    if any(p['browser_main'] or p['GPU_helper'] for p in processes(app)):
        parser.error('quit Zalo normally first; this collector does not close it')
    loaded = command(['/usr/sbin/kextstat', '-l', '-b', 'org.ChefKiss.NootedRed'])
    if loaded.returncode or args.expected_uuid.upper().encode() not in loaded.stdout:
        parser.error('unexpected loaded driver')
    io = command(['ioreg', '-lw0', '-r', '-n', 'IGPU'])
    if io.returncode or not re.search(rb'"NRedVCNContextTraceReady" = 1\b', io.stdout):
        parser.error('context trace is not ready')
    if args.require_vm_trace and not all(re.search(pattern, io.stdout) for pattern in [
            rb'"NRedVMTraceVersion" = 3\b', rb'"NRedVMTraceEnabled" = 1\b',
            rb'"NRedVMTraceRoutes" = 31\b']):
        parser.error('VM trace v3 is not fully ready; no application launched')
    before = gpu_events()
    if before:
        parser.error('this boot already has GPU failures; no fresh workload should be started')
    ring = command(['sudo', '-n', '/sbin/dmesg'])
    if ring.returncode:
        parser.error('sudo -v is required for capture')
    out = ROOT/'build/zalo-freeze-20261026'/f'original-startup-{dt.datetime.now():%Y%m%d-%H%M%S}'
    out.mkdir(mode=0o700)
    record(out/'REQUEST.json', {
        'started_at': dt.datetime.now().astimezone().isoformat(),
        'boot_uuid': command(['sysctl', '-n', 'kern.bootsessionuuid']).stdout.decode().strip(),
        'expected_driver_uuid': args.expected_uuid.upper(),
        'Zalo_version': identity['version'], 'Zalo_build': identity['build'],
        'Electron_version': identity['Electron_version'],
        'app_launch_mode': 'LaunchServices original application after capture ready' if args.launch_original else 'user opens original application',
        'collector_starts_app': args.launch_original, 'captures_messenger_stdout': False})
    save(out/'ioreg-before.txt', io.stdout)
    save(out/'loaded-kext.txt', loaded.stdout)
    save(out/'dmesg-before.txt', ring.stdout)
    baseline_contexts = summarize(ring.stdout.decode(errors='replace'))
    record(out/'context-trace-before.json', baseline_contexts)
    record(out/'before-GPU-events.json', before)
    live = (out/'live-system.ndjson').open('wb', buffering=0)
    predicate = f'({GPU_PREDICATE}) OR (process == "kernel" AND (eventMessage CONTAINS[c] "VCN" OR eventMessage CONTAINS[c] "VMTrace" OR eventMessage CONTAINS[c] "GPU")) OR process == "VTDecoderXPCService"'
    stream = subprocess.Popen(['/usr/bin/log', 'stream', '--style', 'ndjson', '--level', 'info',
                               '--predicate', predicate], stdout=live, stderr=subprocess.STDOUT)
    record(out/'READY.json', {'stream_pid': stream.pid, 'seconds': args.seconds})
    print(f'READY: Open the original /Applications/Zalo.app now. Capture: {out}', flush=True)
    start = time.monotonic()
    observations, errors, snapshots = [], [], 0
    trace_lines = set()
    vm_lines = set()
    last = None
    try:
        if args.launch_original:
            if stream.poll() is not None:
                raise RuntimeError('live system log exited before application launch')
            record(out/'LAUNCH.json', {'epoch': time.time(), 'app': str(app), 'HEVC_guard_requested': False})
            launch_original_app(app)
        while time.monotonic() - start < args.seconds:
            if stream.poll() is not None:
                errors.append('live system log exited'); break
            ring = command(['sudo', '-n', '/sbin/dmesg'], timeout=5)
            if ring.returncode:
                errors.append('kernel capture failed'); break
            if ring.stdout != last:
                save(out/f'dmesg-{snapshots:04d}.txt', ring.stdout)
                snapshots += 1
                last = ring.stdout
                text = ring.stdout.decode(errors='replace')
                trace_lines.update(line for line in text.splitlines() if 'VCNTrace' in line)
                vm_lines.update(line for line in text.splitlines() if re.search(r'\bVMTrace:\s*@', line))
                save(out/'VM-trace-lines.txt', ('\n'.join(sorted(vm_lines))+'\n').encode())
                record(out/'context-trace.json', summarize('\n'.join(sorted(trace_lines))))
            current = processes(app)
            observations.append({'epoch': time.time(), 'processes': current})
            record(out/'process-observations.json', observations)
            if any(p['GPU_helper'] and p['HEVC_feature_disable_forwarded'] for p in current):
                errors.append('HEVC guard found in GPU helper; this is not the requested original-app test'); break
            # Stop collection on a retained hardware fault, without trying to
            # restart the GPU, kill Zalo or submit another workload.
            if re.search(r'(?:GPURestartBegin|channel \d+ .*is hung!|channel \d+ .*event timeout)', ring.stdout.decode(errors='replace')):
                errors.append('GPU fault appeared in kernel ring'); break
            time.sleep(0.25)
    except (subprocess.TimeoutExpired, OSError, RuntimeError) as error:
        errors.append(str(error))
    finally:
        stream.terminate()
        try:
            stream.wait(timeout=2)
        except subprocess.TimeoutExpired:
            stream.kill()
            stream.wait(timeout=2)
        os.fsync(live.fileno())
        live.close()
    try:
        after = gpu_events()
        log_error = None
    except Exception as error:
        after = []
        log_error = str(error)
    record(out/'after-GPU-events.json', after)
    io = command(['ioreg', '-lw0', '-r', '-n', 'IGPU'])
    save(out/'ioreg-after.txt', io.stdout)
    helpers = [p for row in observations for p in row['processes'] if p['GPU_helper']]
    result = {
        'ended_at': dt.datetime.now().astimezone().isoformat(),
        'kernel_snapshots': snapshots, 'capture_errors': errors,
        'GPU_log_error': log_error, 'GPU_failure_events_after': len(after),
        'Zalo_GPU_helper_seen': bool(helpers),
        'HEVC_disable_guard_absent_from_observed_helpers': bool(helpers) and all(not p['HEVC_feature_disable_forwarded'] for p in helpers),
        'context_trace': summarize('\n'.join(sorted(trace_lines))),
        'VM_trace_required': args.require_vm_trace, 'VM_trace_lines': len(vm_lines),
        'VM_native_false_result_lines': [line for line in sorted(vm_lines) if re.search(r'\bresult=0\b', line)],
        'effective_HEVC_runtime_state_verified': False,
        'user_window_check_required': True, 'driver_fix_verified': False}
    existing = {(p['pid'], p['event']) for p in baseline_contexts['events']}
    result['new_context_events'] = [p for p in result['context_trace']['events']
                                    if (p['pid'], p['event']) not in existing]
    record(out/'SUMMARY.json', result)
    print(json.dumps({k: v for k, v in result.items() if k != 'context_trace'}, indent=2), flush=True)
    print('Saved:', out, flush=True)
    return 1 if errors or log_error or after or not helpers else 0


if __name__ == '__main__':
    raise SystemExit(main())
