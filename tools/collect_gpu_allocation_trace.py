#!/usr/bin/env python3
"""Read bounded AllocTrace records; preserve uncertainty about native recovery."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
FAIL=re.compile(r'allocation-fail serial=(\d+) tid=(\d+) physical=(\d+) outer=(\d+) pid=(\d+) name=(.*?) bytes=(\d+) align=(\d+) minBlock=(\d+) origin=(\d+) operation=(\d+) noFixed=(\d+) caller=(0x[0-9a-fA-F]+)')
PHYSICAL=re.compile(r'physical-end tid=(\d+) physical=(\d+) failedRequests=(\d+) sampled=(\d+) result=(\d+) flags=(0x[0-9a-fA-F]+)')
PAGING=re.compile(r'pageon-end tid=(\d+) outer=(\d+) failures=(\d+) sampled=(\d+) flagsBefore=(0x[0-9a-fA-F]+) flagsAfter=(0x[0-9a-fA-F]+) options=(0x[0-9a-fA-F]+) caller=(0x[0-9a-fA-F]+)')
BACKTRACE=re.compile(r'backtrace serial=(\d+) frame=(\d+) pc=(0x[0-9a-fA-F]+)')

def parse_trace(messages):
    failures={};physical={};paging={};stacks={};conflicts=[];unparsed=[];limited=False
    def put(table,key,value):
        if key in table and table[key]!=value:conflicts.append(str(key))
        else:table[key]=value
    for text in messages:
        if 'AllocTrace' not in text:continue
        limited|='detail limit reached' in text
        m=FAIL.search(text)
        if m:
            a=m.groups();row=dict(zip(('serial','tid','physical','outer','pid'),map(int,a[:5])))
            row['current_process_name']=a[5]
            row.update(dict(zip(('bytes','alignment','minimum_block','origin','operation','no_fixed'),map(int,a[6:12]))))
            row['caller']=int(a[12],16);put(failures,row['serial'],row);continue
        m=PHYSICAL.search(text)
        if m:
            a=m.groups();row=dict(zip(('tid','physical','failed_requests','sampled','native_result'),map(int,a[:5])))
            row['allocation_flags']=int(a[5],16);put(physical,(row['tid'],row['physical']),row);continue
        m=PAGING.search(text)
        if m:
            a=m.groups();row=dict(zip(('tid','outer','failed_requests','sampled'),map(int,a[:4])))
            row.update(dict(zip(('flags_before','flags_after','options','caller'),(int(v,16) for v in a[4:]))));put(paging,(row['tid'],row['outer']),row);continue
        m=BACKTRACE.search(text)
        if m:
            serial,frame,pc=m.groups();put(stacks,(int(serial),int(frame)),int(pc,16));continue
        if any(word in text for word in ('allocation-fail','physical-end','pageon-end','backtrace')):unparsed.append(text)
    rows=[]
    for serial,row in sorted(failures.items()):
        row=dict(row)
        row['physical_outcome']=physical.get((row['tid'],row['physical'])) if row['physical'] else None
        row['resource_paging_state']=paging.get((row['tid'],row['outer'])) if row['outer'] else None
        row['backtrace']=[{'frame':frame,'pc':pc} for (event,frame),pc in sorted(stacks.items()) if event==serial]
        rows.append(row)
    return {'failed_native_requests':rows,'conflicting_records':conflicts,'unparsed_trace_records':unparsed,
        'detail_limit_reached':limited,'incomplete_physical_pairs':[x['serial'] for x in rows if x['physical'] and x['physical_outcome'] is None],
        'interpretation':'Current-process identity can be a kernel worker, not the originating app. pageon returns void; resource state words are observations, not an invented success result. A native allocation failure does not alone prove application-visible failure.'}

def symbolize(rows,loaded):
    from gen_vcn_kernel_data import KernelCollection,KextSlice,DEFAULT_KC
    kc=KernelCollection(DEFAULT_KC);modules=[];cache={}
    for line in loaded.splitlines():
        m=re.match(r'\s*\d+\s+\d+\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s+0x[0-9a-fA-F]+\s+(\S+)\s+\([^)]*\)\s+([A-Fa-f0-9-]{36})',line)
        if m:modules.append((int(m[1],16),int(m[2],16),m[3],m[4].replace('-','').lower()))
    def address(pc):
        for base,size,name,uuid in modules:
            if not base<=pc<base+size or name not in kc.fileset_entries:continue
            if name not in cache:
                try:cache[name]=KextSlice(kc,name,*kc.fileset_entries[name])
                except RuntimeError:cache[name]=None
            k=cache[name]
            if k is None or k.uuid.hex()!=uuid:return {'module':name,'status':'UUID mismatch/unavailable; unsymbolized'}
            native=k.text_vmaddr+pc-base
            if not k.text_vmaddr<=native<k.text_vmaddr+k.text_vmsize:return {'module':name,'status':'outside text'}
            fn=k.enclosing_function(native)
            if fn:return {'module':name,'nearest_preceding_CXX_symbol':fn[1],'offset':hex(native-fn[0]),'native_pc':hex(native),'status':'matching loaded UUID; nearest-symbol inference, function boundaries unverified'}
        return {'status':'No matching loaded KC module; unsymbolized'}
    for row in rows:
        row['caller_symbol']=address(row['caller'])
        for frame in row['backtrace']:frame['symbol']=address(frame['pc'])

def ring_messages(features, captures, boot, allow_partial=False):
    """Use only files bound to this boot by their capture's session checks."""
    messages=[];sources=[]
    for path in features:
        metadata=json.loads((path/'SUMMARY.json').read_text())
        if metadata.get('boot_session_uuid')!=boot or not metadata.get('boot_session_continuity_verified'):
            raise ValueError('Feature kernel ring has unverified boot provenance: '+str(path))
        data=path/'dmesg.txt'
        if not data.exists() or not metadata.get('dmesg_captured'):
            raise ValueError('Feature kernel ring was not successfully captured: '+str(path))
        messages.extend(data.read_text(errors='replace').splitlines());sources.append(str(data))
    for path in captures:
        metadata=json.loads((path/'SUMMARY.json').read_text())
        if metadata.get('boot_session_uuid')!=boot or not metadata.get('same_boot') or (metadata.get('errors') and not allow_partial):
            raise ValueError('Live kernel ring has unverified/failed capture provenance: '+str(path))
        if metadata.get('errors') and not metadata.get('samples'):raise ValueError('Partial kernel ring has no successful samples')
        data=path/metadata['file']
        if data.resolve().parent!=path.resolve():raise ValueError('Unexpected kernel ring filename')
        messages.extend(data.read_text(errors='replace').splitlines());sources.append(str(data))
    return list(dict.fromkeys(messages)),sources

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--features',type=Path,required=True);parser.add_argument('--stream',type=Path);parser.add_argument('--earlier-features',type=Path,action='append',default=[]);parser.add_argument('--ring-capture',type=Path,action='append',default=[]);parser.add_argument('--allow-partial-ring',action='store_true',help='Analyze successful same-boot samples preceding a read error; always mark evidence incomplete');a=parser.parse_args()
    os.umask(0o077);a.out.mkdir(parents=True,mode=0o700,exist_ok=True)
    feature=json.loads((a.features/'SUMMARY.json').read_text());boot=feature['boot_session_uuid'];props=feature.get('NRed_properties_after',feature['NRed_properties'])
    predicate='process == "kernel" AND (eventMessage CONTAINS "AllocTrace" OR eventMessage CONTAINS "AMD ERROR! Failed to allocate" OR eventMessage CONTAINS "GPURestartBegin" OR eventMessage CONTAINS "GPU hang:")'
    r=subprocess.run(['/usr/bin/log','show','--last','boot','--style','ndjson','--info','--predicate',predicate],capture_output=True,text=True,timeout=90)
    (a.out/'kernel-private.ndjson').write_text(r.stdout);(a.out/'kernel.stderr').write_text(r.stderr)
    all_events=[]
    sources=[r.stdout]
    if a.stream and a.stream.exists():sources.append(a.stream.read_text(errors='replace'))
    seen=set()
    for source in sources:
        for line in source.splitlines():
            try:row=json.loads(line)
            except ValueError:continue
            if row.get('bootUUID')!=boot or 'eventMessage' not in row:continue
            key=(row.get('machTimestamp'),row.get('threadID'),row['eventMessage'])
            if key not in seen:all_events.append(row);seen.add(key)
    unified_messages=[x['eventMessage'] for x in all_events]
    ring,ring_sources=ring_messages([a.features,*a.earlier_features],a.ring_capture,boot,a.allow_partial_ring)
    ring_errors={str(p):json.loads((p/'SUMMARY.json').read_text()).get('errors',[]) for p in a.ring_capture}
    messages=unified_messages+ring;trace=parse_trace(messages)
    symbolize(trace['failed_native_requests'],(a.features/'loaded-kexts.txt').read_text())
    current=subprocess.check_output(['sysctl','-n','kern.bootsessionuuid'],text=True).strip()
    summary={'captured_at':datetime.datetime.now().astimezone().isoformat(),'boot_session':boot,
        'same_boot':boot==current,'trace_ready':props.get('NRedAllocTraceEnabled')==1 and props.get('NRedAllocTraceRoutes')==7 and props.get('NRedAllocTraceVersion')==1,
        'kernel_log_returncode':r.returncode,'native_warning_lines':sum('AMD ERROR! Failed to allocate' in x for x in unified_messages),
        'native_warning_lines_in_retained_kernel_ring':sum('AMD ERROR! Failed to allocate' in x for x in ring),
        'kernel_ring_sources':ring_sources,'kernel_ring_capture_errors':ring_errors,'warning_count_note':'Unified log and retained ring counts may overlap; do not add them.',
        'GPU_restart_begin_lines':sum(x.count('GPURestartBegin') for x in messages),'GPU_hang_observed':any('GPU hang:' in x for x in messages),
        'failed_requests_captured':len(trace['failed_native_requests']),**trace}
    summary['attribution_observed']=bool(trace['failed_native_requests'])
    summary['warning_to_trace_coverage_incomplete']=max(summary['native_warning_lines'],summary['native_warning_lines_in_retained_kernel_ring'])>len(trace['failed_native_requests'])
    summary['native_warnings_without_failed_request_records']=(summary['native_warning_lines']>0 or summary['native_warning_lines_in_retained_kernel_ring']>0) and not summary['attribution_observed']
    summary['evidence_complete']=not any((trace['conflicting_records'],trace['unparsed_trace_records'],trace['incomplete_physical_pairs'],trace['detail_limit_reached'],summary['native_warnings_without_failed_request_records'],summary['warning_to_trace_coverage_incomplete'],any(ring_errors.values())))
    (a.out/'SUMMARY-private.json').write_text(json.dumps(summary,indent=2)+'\n')
    display={k:v for k,v in summary.items() if k not in ('failed_native_requests','unparsed_trace_records')}
    display['current_processes']=sorted({(x['pid'],x['current_process_name']) for x in trace['failed_native_requests']})
    print(json.dumps(display,indent=2));return 0 if summary['same_boot'] and summary['trace_ready'] and r.returncode==0 and summary['evidence_complete'] else 1

if __name__=='__main__':raise SystemExit(main())
