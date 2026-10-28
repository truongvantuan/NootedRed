#!/usr/bin/env python3
"""Regression checks preventing false patch-verification passes; no GPU access."""
from copy import deepcopy
from pathlib import Path
import re
import hashlib
import os
import struct
import sys
import tempfile
import time
from test_gl_semantic_data import load_arrays
from verify_weachy_features import expected_gl_pages,validate_cache,validate_video_cache,video_exercises,deployment_video_profile_matches,parse_boot_session,command,properties,KernelEvidence,vm_trace_events,embedded_signature_command,vm_trace_ready,vm_mapping_details,traced_gl_command,sleep_evidence,report_time,report_provenance,opencore_log_evidence

ROOT=Path(__file__).resolve().parents[1]
from verify_weachy_features import video_mode
assert video_mode([])=='-NRedVDA'
assert video_mode(['-NRedNoVDA','-NRedVDA']) is None
assert video_mode(['-NRedNoHEVC','-NRedAVCEncode'])=='-NRedAVC'
assert video_mode(['-NRedAVCEncode'])=='-NRedAVCEncode'
arrays=load_arrays(ROOT/'NootedRed/UserPatches.cpp')
for mode,decode_fallback,encode_fallback in [('-NRedVDA',False,False),('-NRedAVC',True,True),('-NRedAVCEncode',True,False)]:
    plan=video_exercises(mode)
    assert len(plan)==4 and len({row[0] for row in plan})==4
    assert {row[2] for row in plan if row[0].startswith('h264')}=={'--decode-h264','--encode-h264'}
    assert next(row[2] for row in plan if row[0].startswith('hevc-decode')).endswith('-fallback')==decode_fallback
    assert next(row[2] for row in plan if row[0].startswith('hevc-encode')).endswith('-fallback')==encode_fallback
assert not video_exercises(None) and not video_exercises('-unknown')
control={'required_video_mode':'-NRedAVC','expected_video_properties':{'NRedVDAAVCOnly':1,'NRedVDAHEVCEncodeAllowed':0}}
avc_props=control['expected_video_properties']
assert deployment_video_profile_matches(control,'-NRedAVC',avc_props)
assert not deployment_video_profile_matches(control,'-NRedVDA',avc_props)
assert not deployment_video_profile_matches(control,'-NRedAVC',{'NRedVDAAVCOnly':1})
assert not deployment_video_profile_matches(control,'-NRedAVC',dict(avc_props,NRedVDAHEVCEncodeAllowed=1))
assert deployment_video_profile_matches({},None,{})
boot_id='c1f0af9d-724c-4839-823e-fd8268391859'
assert parse_boot_session({'returncode':0,'stdout':boot_id+'\n'})==boot_id.upper()
for result in ({'returncode':1,'stdout':boot_id},{'returncode':124,'stdout':boot_id},
               {'returncode':0,'stdout':'prefix '+boot_id},{'returncode':0,'stdout':''},
               {'returncode':0,'stdout':boot_id+' extra'}):
    assert parse_boot_session(result) is None
page=bytearray(arrays['kMTLControlPage_Sequoia']);page[0x164:0x166]=bytes.fromhex('eb0b')
text=(ROOT/'NootedRed/UserSubmitGuard.hpp').read_text()
payload=bytearray(int(x,16) for x in re.findall(r'0x([0-9a-fA-F]{2})',
    re.search(r'UInt8 Payload\[\] = \{(.*?)\};',text,re.S)[1]))
method=0x7ffb20000000;target=0x100000000
struct.pack_into('<Q',payload,296,method+15)
snapshot={'cache_uuid_hex':'42ec2890bc40317ebb2745142bff7f26','metal_page_hex':page.hex(),
          'submit_guard_method_address':method,'submit_guard_target':target,
          'submit_guard_entry_hex':(bytes.fromhex('ff2500000000')+struct.pack('<Q',target)+b'\x90').hex(),
          'submit_guard_payload_hex':payload.hex(),'submit_guard_payload_protection':5}
assert all(validate_cache(snapshot,arrays,24).values())
# A 24H232 UUID alone is insufficient: require its full reference-page variant
# and retain independent entry/payload checks.
new_snapshot=deepcopy(snapshot)
new_snapshot['cache_uuid_hex']='90db0deb23443601b011b87312d74cfb'
assert not all(validate_cache(new_snapshot,arrays,24).values())
new_page=bytearray(page);new_page[0x92c]=0xc8
new_snapshot['metal_page_hex']=new_page.hex()
assert all(validate_cache(new_snapshot,arrays,24).values())
bad_new=deepcopy(new_snapshot);bad_new['metal_page_hex']='00'+new_page.hex()[2:]
assert not all(validate_cache(bad_new,arrays,24).values())
for key,bad in [('cache_uuid_hex','00'*16),('metal_page_hex',('00'+page.hex()[2:])),
                ('submit_guard_entry_hex','ff2500000000'+'00'*9),
                ('submit_guard_payload_hex','00'+payload.hex()[2:]),
                ('submit_guard_payload_protection',7),('submit_guard_target',0)]:
    mutated=deepcopy(snapshot);mutated[key]=bad
    assert not all(validate_cache(mutated,arrays,24).values()),key
# Correct payload bytes with another method's continuation are still invalid.
mutated=deepcopy(snapshot);mutated['submit_guard_method_address']+=4096
assert not validate_cache(mutated,arrays,24)['SubmitGuard_payload_matches']
assert not all(validate_cache(snapshot,arrays,26).values())
assert not all(validate_cache({},arrays,24).values())
from gen_vda_va_data import parse_header
va_text=(ROOT/'NootedRed/VDAVADataSequoia.hpp').read_text()
va_arrays,va_records=parse_header(va_text)
offsets=[int(v,16) for v in re.findall(r'// Page \d+:.*?image offset 0x([0-9A-Fa-f]+)',va_text)]
va_pages={f'Page{i}':bytearray(va_arrays[f'Page{i}']) for i in range(len(offsets))}
# Build the fixture from independently recorded absolute sites, not the verifier's search.
sites=re.findall(r'// Sites: (.*?) \(page offset',va_text)
for record,line in zip(va_records,sites):
    for address in re.findall(r'0x[0-9a-f]+',line):
        offset=int(address,16)&4095;replacement=va_arrays[record['replace']]
        va_pages[record['page']][offset:offset+len(replacement)]=replacement
video_snapshot={'cache_uuid_hex':snapshot['cache_uuid_hex'],'video_pages':{
    hex(0x308606000+offset):va_pages[f'Page{i}'].hex() for i,offset in enumerate(offsets)}}
pitch=bytearray(arrays['kVAEncodePitchPage_Sequoia']);pitch[0xaf5:0xaf5+37]=arrays['kVAEncodePitchReplace']
video_snapshot['video_pages']['0x30864c000']=pitch.hex()
assert len(validate_video_cache(video_snapshot,arrays,24))==10
assert all(validate_video_cache(video_snapshot,arrays,24).values())
for key in video_snapshot['video_pages']:
    bad=deepcopy(video_snapshot);bad['video_pages'][key]=f"{int(bad['video_pages'][key][:2],16)^0x80:02x}"+bad['video_pages'][key][2:]
    assert not all(validate_video_cache(bad,arrays,24).values()),key
    bad=deepcopy(video_snapshot);del bad['video_pages'][key]
    assert not all(validate_video_cache(bad,arrays,24).values()),key
bad=deepcopy(video_snapshot);bad['video_pages']['0x30864c000']=arrays['kVAEncodePitchPage_Sequoia'].hex()
assert not all(validate_video_cache(bad,arrays,24).values())
assert not all(validate_video_cache(video_snapshot,arrays,25).values())
assert not all(validate_video_cache({},arrays,24).values())
assert properties('  "NRedSubmitGuardVersion" = 2\n "NRedLegacyBlendApplied" = 1609')=={
    'NRedSubmitGuardVersion':2,'NRedLegacyBlendApplied':1609}
# A previous boot's real sleep and display/wake requests cannot verify this boot.
sleep_log='''2026-10-22 20:11:08 +0700 Sleep               Entering Sleep state due to 'Software Sleep pid=191':TCPKeepAlive=active
2026-10-22 20:13:18 +0700 DarkWake            DarkWake from Normal Sleep [CDNP] : due to XHC0 XHC2/
2026-10-22 20:13:50 +0700 Wake                DarkWake to FullWake from Normal Sleep [CDNVA] : due to UserActivity Assertion
'''
import datetime
stamp=lambda text:datetime.datetime.fromisoformat(text).timestamp()
# A recovery EFI's real injection failure must not be attributed to today's
# RELEASE boot, even if its FAT mtime became newer while copying the file.
oc_failure='21:851 02:607 OC: Prelinked injection ForgedInvariant.kext (ForgedInvariant.kext) - Invalid Parameter'
oc_log='[EB|LOG:INIT] 2026-10-23T16:34:34\n'+oc_failure+'\x00'*10
current_boot=stamp('2026-10-24T09:57:24+07:00')
old_oc=opencore_log_evidence(oc_log,current_boot)
assert old_oc['current_boot_injection_failures'] is None
assert old_oc['retained_file_injection_failures']==[oc_failure]
assert not old_oc['UTC_timing_consistent_with_current_boot']
matching_oc=opencore_log_evidence(oc_log,stamp('2026-10-23T23:35:00+07:00'))
assert matching_oc['current_boot_injection_failures']==[oc_failure]
assert matching_oc['classification']=='current_boot_timing_candidate'
assert 'inference' in matching_oc['boot_provenance']
assert opencore_log_evidence('[EB|LOG:INIT] 2026-10-24T02:57:00\n',current_boot)['current_boot_injection_failures']==[]
for unverified_log in (oc_failure,'[EB|LOG:INIT] 2026-99-99T99:99:99\n'+oc_failure):
    unknown_oc=opencore_log_evidence(unverified_log,current_boot)
    assert unknown_oc['current_boot_injection_failures'] is None
    assert unknown_oc['retained_file_injection_failures']==[oc_failure]
future_oc=opencore_log_evidence(oc_log,stamp('2026-10-22T09:57:24+07:00'))
assert future_oc['current_boot_injection_failures'] is None
start=stamp('2026-10-23T13:08:37+07:00');finish=stamp('2026-10-23T14:00:00+07:00')
zone=datetime.timezone(datetime.timedelta(hours=7))
old_report='Date/Time:           Fri Oct 23 06:53:13 2026\n'
assert report_time(old_report,zone)==(stamp('2026-10-23T06:53:13+07:00'),'embedded_local_time_inference')
assert report_time('Date/Time: 2026-10-23 13:20:00.172 +0700\n')[0]>start
assert report_time('{"timestamp":"2026-10-23 13:20:00.172 +0700"}\n')[0]>start
assert report_time('no report date')==(None,'unavailable')
with tempfile.TemporaryDirectory() as directory:
    old=Path(directory)/'copied-old.spin';old.write_text('Date/Time: 2026-10-23 06:55:59.172 +0700\n')
    current=Path(directory)/'current.ips';current.write_text('{"timestamp":"2026-10-23 13:20:00.172 +0700"}\n')
    unknown=Path(directory)/'unknown.panic';unknown.write_text('unparsed report')
    rows=report_provenance({str(old):[int(finish*1e9),old.stat().st_size],str(current):[0,current.stat().st_size],str(unknown):[int(finish*1e9),unknown.stat().st_size]},start)
    assert not rows[0]['current_boot_or_unresolved']
    assert rows[1]['current_boot_or_unresolved'] and rows[2]['current_boot_or_unresolved']
zero='Sleep Count:0\nDark Wake Count:0\nUser Wake Count:0\n'
assert not sleep_evidence(zero,sleep_log,start,finish)['current_boot_transition_events']
current=sleep_log.replace('2026-10-22 20:11:08','2026-10-23 13:20:08').replace('2026-10-22 20:13:18','2026-10-23 13:22:18').replace('2026-10-22 20:13:50','2026-10-23 13:22:50')
stats=zero.replace('Sleep Count:0','Sleep Count:1')
result=sleep_evidence(stats,sleep_log+current,start,finish)
assert result['system_sleep_cycle_recorded'] and len(result['completed_system_cycles'])==1
assert result['completed_system_cycles'][0]['elapsed_seconds']==162
assert not result['functional_wake_verified']
assert not sleep_evidence(stats,'\n'.join(current.splitlines()[:2]),start,finish)['system_sleep_cycle_recorded']
assert not sleep_evidence(stats,current.splitlines()[-1],start,finish)['system_sleep_cycle_recorded']
assert not sleep_evidence(stats,current,start,stamp('2026-10-23T13:21:00+07:00'))['system_sleep_cycle_recorded']
contradiction=sleep_evidence(zero,current,start,finish)
assert contradiction['counter_log_conflict'] and not contradiction['system_sleep_cycle_recorded']
assert not sleep_evidence(stats,'2026-10-23 13:30:00 +0700 Wake Requests    request=UserWake\n2026-10-23 13:31:00 +0700 Display     Display is turned on',start,finish)['current_boot_transition_events']
# Equivalent UTC timestamps and same-second transitions are handled conservatively.
utc=current.replace('13:20:08 +0700','06:20:08 +0000').replace('13:22:18 +0700','06:22:18 +0000').replace('13:22:50 +0700','06:22:50 +0000')
assert sleep_evidence(stats,utc,start,finish)['system_sleep_cycle_recorded']
assert not sleep_evidence(stats,current.replace('13:22:50','13:20:08'),start,finish)['system_sleep_cycle_recorded']
assert command(['/no/such/nred-diagnostic'])['returncode']==127
result=command([sys.executable,'-c','import time; time.sleep(10)'],timeout=0.05)
assert result['returncode']==124 and result.get('pending_child_pid') is None
with tempfile.TemporaryDirectory() as directory:
    rows=iter(['before GPU submission\n','GPU VM Protection Fault CPG 0x400004000\n','verbose output overwrote fault\n'])
    def kernel_reader(args,timeout):
        assert args==['sudo','-n','/sbin/dmesg'] and timeout==2
        return {'returncode':0,'stdout':next(rows,'verbose output overwrote fault\n'),'stderr':''}
    capture=KernelEvidence(Path(directory),runner=kernel_reader,interval=0.005)
    assert capture.start()
    deadline=time.monotonic()+2
    while len(capture.samples)<3 and time.monotonic()<deadline:time.sleep(0.005)
    evidence=capture.finish()
    assert evidence['error'] is None and len(evidence['samples'])==3
    assert 'Protection Fault' in (Path(directory)/evidence['samples'][1]['file']).read_text()
    assert not capture.thread.is_alive()
with tempfile.TemporaryDirectory() as directory:
    capture=KernelEvidence(Path(directory),runner=lambda *a,**kw:{'returncode':1,'stdout':'','stderr':'sudo timestamp missing'})
    assert not capture.start() and capture.thread is None
    assert capture.finish()['error']['returncode']==1
begin='NootedRed: VMTrace begin op=commit pid=4321 gpuVA=0x400004000 options=0x10 event=17\n'
end='NootedRed: VMTrace end op=commit pid=4321 gpuVA=0x400004000 options=0x50 result=0 event=17\n'
# Repeated kernel-ring snapshots must not invent additional calls or lose changed output options.
trace=vm_trace_events([begin,begin+end,end])
assert trace['complete_operations']==1 and len(trace['events'])==1
assert len(trace['native_false_results'])==1 and trace['events'][0]['end']['options']=='0x50'
assert not trace['conflicting_duplicates']
assert len(vm_trace_events([begin])['incomplete_events'])==1
assert vm_trace_events([begin+end,end.replace('result=0','result=1')])['conflicting_duplicates']
legacy={'NRedVMTraceEnabled':1,'NRedVMTraceRoutes':7}
assert vm_trace_ready(legacy,['-NRedVMTrace']) and not vm_trace_ready(legacy,['-NRedVMTrace'],2)
v2={'NRedVMTraceVersion':2,'NRedVMTraceEnabled':1,'NRedVMTraceRoutes':31}
assert vm_trace_ready(v2,['-NRedVMTrace'],2)
assert not vm_trace_ready(v2,[],2)
assert not vm_trace_ready(dict(v2,NRedVMTraceRoutes=7),['-NRedVMTrace'],2)
assert not vm_trace_ready(dict(v2,NRedVMTraceRejected=2),['-NRedVMTrace'],2)
assert not vm_trace_ready(dict(v2,NRedVMTraceVersion=3),['-NRedVMTrace'],2)
rows=['[ 1.000000]: VMTrace range begin pid=42 tid=10 event=1 gpuVA=0x400000000 size=0x2000 offset=0x0 flags=0x10',
      '[ 1.100000]: VMTrace range begin pid=42 tid=11 event=2 gpuVA=0x400004000 size=0x1000 offset=0x0 flags=0x0',
      '[ 1.200000]: VMTrace pte pid=42 tid=10 event=1 level=0 physical=0x12345000 flags=0x17 fragment=0 value=0x12345067',
      '[ 1.300000]: VMTrace range end pid=42 tid=11 event=2 result=0',
      '[ 1.400000]: VMTrace range end pid=42 tid=10 event=1 result=1']
details=vm_mapping_details(['\n'.join(rows[:3]),'\n'.join(rows),'\n'.join(rows[2:])])
assert details['complete_ranges']==2 and len(details['constructed_entries'])==1
entry=details['constructed_entries'][0]
assert entry['within_range_events']==[1] and entry['constructor_output']['write_bit']
assert not details['ranges'][1]['end']['result'] and not details['conflicting_duplicates']
assert vm_mapping_details(['\n'.join(rows),'\n'.join(rows).replace('value=0x12345067','value=0x12345027')])['conflicting_duplicates']
# A wrapped ring retains the event body but can lose its timestamp prefix.
partial=rows[2].split(']: ',1)[1]
for chunks in ([partial,'\n'.join(rows)],['\n'.join(rows),partial]):
    wrapped=vm_mapping_details(chunks)
    assert not wrapped['conflicting_duplicates']
    assert wrapped['constructed_entries'][0]['constructor_output']['uptime']==1.2
    assert wrapped['constructed_entries'][0]['within_range_events']==[1]
assert vm_mapping_details(['\n'.join(rows),rows[2].replace('1.200000','1.250000')])['conflicting_duplicates']
with tempfile.TemporaryDirectory(prefix='nred trace ') as directory:
    library=Path(directory)/'observer.dylib';library.write_bytes(b'fixture, never loaded')
    manifest={'library':str(library),'sha256':hashlib.sha256(library.read_bytes()).hexdigest()}
    args=traced_gl_command(['probe','--render'],Path(directory),manifest)
    assert args==['/usr/bin/env','DYLD_INSERT_LIBRARIES='+str(library.resolve()),
                  'NRED_GPU_TRACE_DIR='+str(Path(directory).resolve()),'probe','--render']
    assert os.environ.get('DYLD_INSERT_LIBRARIES')!=str(library)
    for bad in (None,dict(manifest,sha256='0'*64),dict(manifest,library=str(library)+'-missing')):
        try:traced_gl_command(['probe'],Path(directory),bad)
        except ValueError:pass
        else:raise AssertionError('Unverified GL API observer accepted')
header=struct.pack('<IiiIIIII',0xfeedfacf,0x1000007,3,6,1,16,0,0)+struct.pack('<IIII',0x1d,16,4096,128)
assert embedded_signature_command(header,4224)==(4096,128)
for bad,size in [(header[:-1],4224),(header,4200),(b'\0'*len(header),4224),
                 (header[:36]+struct.pack('<I',7)+header[40:],4224),
                 (header[:40]+struct.pack('<II',16,128),4224)]:
    try:embedded_signature_command(bad,size)
    except ValueError:pass
    else:raise AssertionError('Accepted malformed or out-of-file signature command')
print('feature verification: foreign UUID/page, malformed entry/payload, wrong continuation, RWX, missing evidence and bounded subprocess failures rejected')
print('kernel evidence: transient fault retained after ring overwrite; missing privilege blocks submission; worker stops')
print('embedded signature: truncated commands, bad architecture/command sizes and invalid file bounds rejected')
print('VM trace v2: strict version/route gates and deduplicated thread/time range association passed')
print('sleep evidence: old boots, display-only, dark-only, unpaired/future transitions and counter conflicts do not pass; physical function remains separate')
print('video pages: all nine complete VA pages required; wrong/missing/stock pitch pages and unsupported references rejected')
print('report provenance: copied old reports do not become new faults; embedded current dates and unresolved fresh reports still block')

# Conditional GL pages must not be accepted as the old short-opcode policy.
for major in (23,24,25):
    old=expected_gl_pages(arrays,major)
    for device in (0x1638,0x15d8,0x15dd,0x15e7,0x1636,0x164c):
        new=expected_gl_pages(arrays,major,device)
        assert len(new)==(3 if major==24 else 2)
        assert all(len(stock)==len(target)==4096 for _,stock,target in new)
        assert all(a[1]==b[1] and a[2]!=b[2] for a,b in zip(old[:2],new[:2]))
        if major==24:assert old[2]==new[2]
try:expected_gl_pages(arrays,24,0xffff)
except KeyError:pass
else:raise AssertionError('Unknown conditional GL device accepted')
print('conditional GL verifier: full per-device pages differ from legacy; budget retained; unknown GPU rejected')
from verify_weachy_features import deployment_gl_profile_matches
required={'required_page_local_GL_revision':5}
props={'NRedOpenGLRevision':5,'NRedOpenGLPageLocal':1,'NRedOpenGLEnabled':1,'NRedOpenGLBackends':3}
assert deployment_gl_profile_matches(required,props)
for key in props:
    bad=props.copy();bad.pop(key);assert not deployment_gl_profile_matches(required,bad)
    bad=props.copy();bad[key]=0;assert not deployment_gl_profile_matches(required,bad)
assert deployment_gl_profile_matches({}, {})
print('conditional GL deployment gate: revision, page-local owner, enable and native hook required before GPU workloads')
