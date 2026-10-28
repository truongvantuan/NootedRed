#!/usr/bin/env python3
"""Inspect or test an app-local HEVC startup-probe guard for Zalo/Electron 22.

Default is inspection only. --run --yes launches Zalo with one disabled feature,
leaving global NootedRed settings and other codecs/graphics controls unchanged.
This is an application workaround, not a repair of the AMD HEVC driver.
"""
import argparse
import datetime as dt
import json
import mmap
import os
import plistlib
import re
import subprocess
import time
from pathlib import Path

FEATURE='PlatformHEVCDecoderSupport'


def plan(app):
    info=plistlib.loads((app/'Contents/Info.plist').read_bytes())
    framework=app/'Contents/Frameworks/Electron Framework.framework/Versions/A/Electron Framework'
    metadata=plistlib.loads((app/'Contents/Frameworks/Electron Framework.framework/Resources/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier')!='com.vng.zalo' or metadata.get('CFBundleVersion')!='22.3.9':
        raise ValueError('Unsupported application/runtime identity; inspect this build before using the guard')
    with framework.open('rb') as f:
        with mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as data:
            if data.find(FEATURE.encode()+b'\0')<0:
                raise ValueError('HEVC feature control is missing from the application runtime')
    binary=app/'Contents/MacOS'/info['CFBundleExecutable']
    return {'application':str(app),'version':info.get('CFBundleShortVersionString'),
            'build':info.get('CFBundleVersion'),'Electron_version':metadata['CFBundleVersion'],
            'disabled_feature':FEATURE,'command':[str(binary),'--disable-features='+FEATURE],
            'global_GPU_configuration_changed':False,'original_app_bundle_modified':False}


def processes(app):
    result=subprocess.run(['ps','-axo','pid=,ppid=,command='],capture_output=True,text=True,check=True)
    rows=[]
    prefix=str(app/'Contents')+'/'
    for line in result.stdout.splitlines():
        match=re.match(r'\s*(\d+)\s+(\d+)\s+(.*)',line)
        if match and match[3].startswith(prefix):
            command=match[3]
            rows.append({'pid':int(match[1]),'ppid':int(match[2]),'GPU_helper':'Zalo Helper (GPU)' in command,
                         'browser_main':command.startswith(str(app/'Contents/MacOS/Zalo')),
                         'disabled_features':re.findall(r'--disable-features=(\S+)',command),
                         'enabled_features':re.findall(r'--enable-features=(\S+)',command),
                         'HEVC_feature_enable_forwarded':any(FEATURE in s.split(',') for s in re.findall(r'--enable-features=(\S+)',command)),
                         'HEVC_feature_disable_forwarded':any(FEATURE in s.split(',') for s in re.findall(r'--disable-features=(\S+)',command))})
    return rows


def activate_or_launch(app, request):
    active=[p for p in processes(app) if p['browser_main'] or p['GPU_helper']]
    if active:
        if not any(p['browser_main'] for p in active) or not all(p['HEVC_feature_disable_forwarded'] for p in active):
            raise ValueError('Zalo is already running without the guard. Quit Zalo, then use this launcher again.')
        subprocess.run(['/usr/bin/open','-a',str(app)],check=True)
        return {'activated_existing_guarded_Zalo':True}
    child=subprocess.Popen(request['command'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    return {'started_guarded_Zalo_PID':child.pid}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--app',type=Path,default=Path('/Applications/Zalo.app'))
    mode=ap.add_mutually_exclusive_group()
    mode.add_argument('--run',action='store_true')
    mode.add_argument('--launch',action='store_true',help='ordinary guarded launch without diagnostic capture or administrator access')
    ap.add_argument('--yes',action='store_true')
    ap.add_argument('--seconds',type=int,default=60)
    ap.add_argument('--out',type=Path)
    ap.add_argument('--test-hevc-enabled',action='store_true',help='diagnostic run with HEVC explicitly enabled; can freeze the PC')
    ap.add_argument('--expected-uuid',help='require this loaded driver identity for the diagnostic run')
    args=ap.parse_args()
    if not 30<=args.seconds<=180:ap.error('capture duration must be 30–180 seconds')
    if args.test_hevc_enabled and (not args.run or not args.yes):
        ap.error('HEVC-enabled experiment requires --run --yes')
    try:request=plan(args.app)
    except (OSError,ValueError,KeyError) as e:ap.error(str(e))
    if args.test_hevc_enabled:
        request['command']=[request['command'][0],'--enable-features='+FEATURE]
        request['disabled_feature']=None
        request['enabled_feature']=FEATURE
    if args.launch:
        try:print(json.dumps(activate_or_launch(args.app,request)))
        except ValueError as e:ap.error(str(e))
        return
    if not args.run:
        print(json.dumps(request,indent=2));return
    if not args.yes:ap.error('launch experiment requires --run --yes and saved work')
    if any(p['browser_main'] or p['GPU_helper'] for p in processes(args.app)):
        ap.error('Zalo is already running; quit it first so an existing process cannot ignore the guard')
    if args.expected_uuid:
        loaded=subprocess.run(['/usr/sbin/kextstat','-l','-b','org.ChefKiss.NootedRed'],capture_output=True)
        if loaded.returncode or args.expected_uuid.upper().encode() not in loaded.stdout:
            ap.error('loaded NootedRed identity does not match this experiment')
    from run_hevc_isolation import gpu_events
    before=gpu_events()
    if before:ap.error('current boot already has GPU failures; no new workload submitted')
    ring=subprocess.run(['sudo','-n','/sbin/dmesg'],capture_output=True)
    if ring.returncode:ap.error('run sudo -v first; kernel capture is required')
    label='hevc-enabled-test' if args.test_hevc_enabled else 'guard-test'
    out=args.out or Path(__file__).resolve().parents[1]/'build/zalo-freeze-20261026'/f'{label}-{dt.datetime.now():%Y%m%d-%H%M%S}'
    out.mkdir(parents=True,mode=0o700,exist_ok=False)
    (out/'REQUEST.json').write_text(json.dumps(request,indent=2)+'\n')
    (out/'before-GPU-events.json').write_text(json.dumps(before,indent=2)+'\n')
    (out/'dmesg-before.txt').write_bytes(ring.stdout)
    (out/'boot-uuid.txt').write_bytes(subprocess.check_output(['sysctl','-n','kern.bootsessionuuid']))
    (out/'ioreg-before.txt').write_bytes(subprocess.check_output(['ioreg','-lw0','-r','-n','IGPU']))
    predicate='(process == "kernel" AND (eventMessage CONTAINS[c] "GPU" OR eventMessage CONTAINS[c] "VCN")) OR process == "VTDecoderXPCService"'
    logfile=(out/'live-system.ndjson').open('wb')
    stream=subprocess.Popen(['/usr/bin/log','stream','--style','ndjson','--level','info','--predicate',predicate],stdout=logfile,stderr=subprocess.STDOUT)
    # Avoid recording messenger stdout, which may contain private account/chat data.
    child=subprocess.Popen(request['command'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    print(f'Zalo {label} launch started; capture: {out}',flush=True)
    start=time.monotonic();saved=0;last=None;observations=[];errors=[]
    try:
        while time.monotonic()-start<args.seconds:
            ring=subprocess.run(['sudo','-n','/sbin/dmesg'],capture_output=True,timeout=5)
            if ring.returncode:
                errors.append('kernel capture failed');break
            if ring.stdout!=last:
                with (out/f'dmesg-{saved:03d}.txt').open('wb') as f:
                    f.write(ring.stdout);f.flush();os.fsync(f.fileno())
                saved+=1;last=ring.stdout
            current=processes(args.app)
            observations.append({'epoch':time.time(),'processes':current})
            (out/'process-observations.json').write_text(json.dumps(observations,indent=2)+'\n')
            if args.test_hevc_enabled:
                if any(p['GPU_helper'] and p['HEVC_feature_disable_forwarded'] for p in current):
                    errors.append('GPU helper unexpectedly has the HEVC-disable guard');break
            elif any(p['GPU_helper'] and not p['HEVC_feature_disable_forwarded'] for p in current):
                errors.append('GPU helper did not inherit HEVC guard');break
            if child.poll() is not None:
                errors.append(f'Zalo launcher process exited with {child.returncode}');break
            time.sleep(0.5)
    finally:
        stream.terminate()
        try:stream.wait(timeout=2)
        except subprocess.TimeoutExpired:stream.kill();stream.wait(timeout=2)
        logfile.close()
    after=gpu_events();gpu=[p for o in observations for p in o['processes'] if p['GPU_helper']]
    (out/'ioreg-after.txt').write_bytes(subprocess.check_output(['ioreg','-lw0','-r','-n','IGPU']))
    summary={'captured_at':dt.datetime.now().astimezone().isoformat(),'application_PID':child.pid,
             'application_still_running':child.poll() is None,'capture_errors':errors,
             'GPU_helper_observed':bool(gpu),'guard_forwarded_to_all_observed_GPU_helpers':bool(gpu) and all(p['HEVC_feature_disable_forwarded'] for p in gpu),
             'GPU_failure_events_before':len(before),'GPU_failure_events_after':len(after),
             'new_GPU_failure_events':max(0,len(after)-len(before)),'kernel_ring_snapshots':saved,
             'functional_window_check_required':True,'hardware_HEVC_driver_fixed':False,
             'actual_H264_decoder_backend_verified':False}
    summary['HEVC_explicitly_enabled_test']=args.test_hevc_enabled
    summary['HEVC_enable_forwarded_to_all_observed_GPU_helpers']=bool(gpu) and all(p['HEVC_feature_enable_forwarded'] and not p['HEVC_feature_disable_forwarded'] for p in gpu)
    summary['HEVC_effective_runtime_state_verified']=summary['HEVC_enable_forwarded_to_all_observed_GPU_helpers']
    summary['HEVC_state_note']='Explicit enable forwarding is required for verification; an absent disable flag alone does not verify runtime state.'
    (out/'after-GPU-events.json').write_text(json.dumps(after,indent=2)+'\n')
    (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
