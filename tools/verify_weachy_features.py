#!/usr/bin/env python3
"""Collect release-feature evidence; submit GPU work only with explicit --exercise-* options."""
import argparse
import ctypes
import datetime
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import signal
import time
import struct
import subprocess
import sys
import threading
from test_gl_semantic_data import load_arrays

ROOT = Path(__file__).resolve().parents[1]

def command(args, timeout=40):
    own_session = Path(args[0]).name != 'sudo'
    try:
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=own_session)
    except OSError as error:
        return {'returncode':127,'stdout':'','stderr':str(error)}
    try:
        stdout,stderr = process.communicate(timeout=timeout)
        return {'returncode':process.returncode,'stdout':stdout.decode(errors='replace'),
                'stderr':stderr.decode(errors='replace')}
    except subprocess.TimeoutExpired as error:
        try:
            if own_session: os.killpg(process.pid, signal.SIGKILL)
            else: process.kill()
        except ProcessLookupError: pass
        try:
            stdout,stderr = process.communicate(timeout=1)
            pending = None
        except subprocess.TimeoutExpired:
            stdout,stderr = error.stdout or b'',error.stderr or b''
            pending = process.pid
        return {'returncode':124,'stdout':stdout.decode(errors='replace'),
                'stderr':stderr.decode(errors='replace')+'\nTimed out; termination requested',
                'pending_child_pid':pending}

def save_command(out, name, args, timeout=40):
    result = command(args, timeout)
    (out/(name+'.txt')).write_text(result['stdout'])
    (out/(name+'.stderr')).write_text(result['stderr'])
    return result

def parse_boot_session(result):
    value=result.get('stdout','').strip()
    if result.get('returncode')==0 and re.fullmatch(r'[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}',value):
        return value.upper()
    return None

def traced_gl_command(invocation, directory, manifest):
    """Scope an optional, hash-verified API observer to this probe process only."""
    if not manifest:raise ValueError('GL API observer is not recorded in the deployment')
    library=Path(manifest['library']).resolve()
    if not library.is_file() or hashlib.sha256(library.read_bytes()).hexdigest()!=manifest['sha256']:
        raise ValueError('GL API observer is missing or its binary hash changed')
    directory=directory.resolve()
    return ['/usr/bin/env','DYLD_INSERT_LIBRARIES='+str(library),
            'NRED_GPU_TRACE_DIR='+str(directory),*invocation]

class KernelEvidence:
    """Read the bounded kernel ring during a probe, before verbose logs overwrite a fault."""
    def __init__(self, out, runner=None, interval=0.5):
        self.out=out
        self.runner=runner or command
        self.interval=interval
        self.stop=threading.Event()
        self.thread=None
        self.digest=None
        self.samples=[]
        self.error=None

    def sample(self):
        try:
            result=self.runner(['sudo','-n','/sbin/dmesg'],timeout=2)
            data=result['stdout'].encode()
            if result['returncode']!=0 or not data:
                self.error={'returncode':result['returncode'],'stderr':result['stderr']}
                return False
            if len(data)>1024*1024 or len(self.samples)>=192:
                self.error={'reason':'Kernel evidence capture size limit reached'}
                return False
            digest=hashlib.sha256(data).hexdigest()
            if digest!=self.digest:
                filename=f'dmesg-{len(self.samples):03d}.txt'
                (self.out/filename).write_bytes(data)
                self.samples.append({'file':filename,'captured_at':datetime.datetime.now().astimezone().isoformat(),
                                     'sha256':digest,'bytes':len(data)})
                self.digest=digest
            return True
        except Exception as error:
            self.error={'reason':str(error)}
            return False

    def start(self):
        self.out.mkdir(mode=0o700,parents=True,exist_ok=True)
        if not self.sample():return False
        def capture():
            while not self.stop.wait(self.interval):
                if not self.sample():break
        self.thread=threading.Thread(target=capture,daemon=True)
        self.thread.start()
        return True

    def finish(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=4)
            if self.thread.is_alive():self.error={'reason':'Kernel evidence worker did not terminate within deadline'}
        if not self.error:self.sample()
        result={'samples':self.samples,'error':self.error,'interval_seconds':self.interval}
        (self.out/'INDEX.json').write_text(json.dumps(result,indent=2)+'\n')
        return result

def properties(text):
    return {key:int(value) for key,value in re.findall(r'"(NRed[^"\n]+)"\s*=\s*(\d+)',text)}

def sleep_evidence(stats, log, boot_epoch, captured_epoch):
    """Report current-boot OS transitions separately from successful physical wake."""
    counts={name:int(value) for name,value in re.findall(
        r'^(Sleep Count|Dark Wake Count|User Wake Count):\s*(\d+)\s*$',stats,re.M)}
    events=[];cycles=[];pending=None
    for line in log.splitlines():
        match=re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{4})\s+(Sleep|DarkWake|Wake)\s+(.+)$',line)
        if not match:continue
        try:epoch=datetime.datetime.strptime(match[1],'%Y-%m-%d %H:%M:%S %z').timestamp()
        except ValueError:continue
        if not boot_epoch<=epoch<=captured_epoch:continue
        kind,detail=match[2],match[3].strip()
        if kind=='Sleep' and 'Entering Sleep state' not in detail:continue
        if kind in ('Wake','DarkWake') and not re.search(r'\bfrom (?:Normal |Deep Idle |Standby |Hibernate |Safe )?Sleep\b',detail):continue
        event={'timestamp':match[1],'epoch':epoch,'kind':kind,'detail':detail}
        events.append(event)
    # A new sleep supersedes an earlier incomplete transition. Dark wakes alone
    # never count as a return to the interactive desktop.
    for event in sorted(events,key=lambda row:row['epoch']):
        if event['kind']=='Sleep':pending=event
        elif event['kind']=='Wake' and pending and event['epoch']>pending['epoch']:
            cycles.append({'sleep':pending,'wake':event,'elapsed_seconds':event['epoch']-pending['epoch']})
            pending=None
    contradiction=bool(cycles) and counts.get('Sleep Count')==0
    return {'counts':counts,'current_boot_transition_events':events,'completed_system_cycles':cycles,
            'system_sleep_cycle_recorded':bool(cycles) and counts.get('Sleep Count',0)>0,
            'counter_log_conflict':contradiction,'functional_wake_verified':False,
            'interpretation':'OS transition evidence only; verify desktop, rendering and devices after physical wake separately. Display off/on and older-boot events do not verify this boot.'}

def vm_trace_events(chunks):
    events={}
    conflicts=[]
    pattern=re.compile(r'\b(begin|end) op=(assign|commit|update) pid=(\d+) gpuVA=(0x[0-9A-Fa-f]+) options=(0x[0-9A-Fa-f]+)(?: result=([01]))? event=(\d+)')
    for chunk in chunks:
        for match in pattern.finditer(chunk):
            phase,operation,pid,address,options,result,event=match.groups()
            key=(int(pid),int(event)); row={'operation':operation,'GPU_address':address.lower(),'options':options.lower()}
            if result is not None:row['result']=result=='1'
            entry=events.setdefault(key,{'pid':key[0],'event':key[1]})
            if phase in entry and entry[phase]!=row:
                conflicts.append({'pid':key[0],'event':key[1],'phase':phase})
            entry[phase]=row
    ordered=sorted(events.values(),key=lambda row:row['event'])
    complete=[row for row in ordered if 'begin' in row and 'end' in row
              and row['begin']['operation']==row['end']['operation']]
    return {'events':ordered,'complete_operations':len(complete),
            'native_false_results':[row for row in complete if not row['end'].get('result',True)],
            'incomplete_events':[row for row in ordered if row not in complete],
            'conflicting_duplicates':conflicts,
            'interpretation':'Native mapping return values are observations; even true is not proof of residency or GPU access at execution time'}

def vm_trace_ready(props, args, minimum_version=1):
    version=props.get('NRedVMTraceVersion',1)
    required={1:7,2:31}.get(version)
    return ('-NRedVMTrace' in args and required is not None and version>=minimum_version
            and props.get('NRedVMTraceEnabled')==1 and props.get('NRedVMTraceRoutes')==required
            and not props.get('NRedVMTraceRejected',0))

def vm_mapping_details(chunks):
    ranges={};entries={};conflicts=[]
    begin=re.compile(r'range begin pid=(\d+) tid=(\d+) event=(\d+) gpuVA=(0x[0-9A-Fa-f]+) size=(0x[0-9A-Fa-f]+) offset=(0x[0-9A-Fa-f]+) flags=(0x[0-9A-Fa-f]+)')
    end=re.compile(r'range end pid=(\d+) tid=(\d+) event=(\d+) result=([01])')
    pte=re.compile(r'pte pid=(\d+) tid=(\d+) event=(\d+) level=(\d+) physical=(0x[0-9A-Fa-f]+) flags=(0x[0-9A-Fa-f]+) fragment=(\d+) value=(0x[0-9A-Fa-f]+)')
    def put(collection,key,phase,row):
        record=collection.setdefault(key,{'pid':key[0],'event':key[1]})
        if phase in record:
            previous=record[phase]
            # The ring can start halfway through a line after wraparound. An
            # otherwise identical event without its timestamp is weaker evidence,
            # not a second native result. Retain the intact timestamp for pairing.
            previous_body={k:v for k,v in previous.items() if k!='uptime'}
            body={k:v for k,v in row.items() if k!='uptime'}
            if previous_body==body and (previous['uptime'] is None or row['uptime'] is None):
                if row['uptime'] is None:row=previous
            elif previous!=row:conflicts.append({'pid':key[0],'event':key[1],'kind':phase})
        record[phase]=row
    for chunk in chunks:
        for line in chunk.splitlines():
            if 'VMTrace' not in line:continue
            stamp=re.search(r'\[\s*(\d+\.\d+)\]',line)
            when=float(stamp[1]) if stamp else None
            match=begin.search(line)
            if match:
                pid,thread,event,address,size,offset,flags=match.groups()
                put(ranges,(int(pid),int(event)),'begin',{'thread':int(thread),'uptime':when,
                    'GPU_address':int(address,16),'size':int(size,16),'memory_offset':int(offset,16),'flags':int(flags,16)})
                continue
            match=end.search(line)
            if match:
                pid,thread,event,result=match.groups()
                put(ranges,(int(pid),int(event)),'end',{'thread':int(thread),'uptime':when,'result':result=='1'})
                continue
            match=pte.search(line)
            if match:
                pid,thread,event,level,physical,flags,fragment,value=match.groups();value=int(value,16)
                put(entries,(int(pid),int(event)),'constructor_output',{'thread':int(thread),'uptime':when,
                    'level':int(level),'physical':int(physical,16),'flags':int(flags,16),'fragment':int(fragment),
                    'value':value,'valid_bit':bool(value&1),'read_bit':bool(value&(1<<5)),'write_bit':bool(value&(1<<6))})
    complete=[]
    for row in ranges.values():
        if 'begin' in row and 'end' in row and row['begin']['thread']==row['end']['thread']:
            complete.append(row)
    for row in entries.values():
        output=row['constructor_output'];when=output['uptime']
        row['within_range_events']=[r['event'] for r in complete if r['pid']==row['pid']
            and r['begin']['thread']==output['thread'] and when is not None
            and r['begin']['uptime'] is not None and r['end']['uptime'] is not None
            and r['begin']['uptime']<=when<=r['end']['uptime']]
    return {'ranges':sorted(ranges.values(),key=lambda r:r['event']),
            'constructed_entries':sorted(entries.values(),key=lambda r:r['event']),
            'complete_ranges':len(complete),'conflicting_duplicates':conflicts,
            'interpretation':'Thread/time association locates constructor calls within native mapping calls. Constructor outputs are not a readback of installed or GPU-visible page tables.'}

def gpu_reports():
    result={}
    root=Path('/Library/Logs/DiagnosticReports')
    for pattern in ('*.gpuRestart','WindowServer*.ips','WindowServer*watchdog*.spin','*.panic'):
        for path in root.glob(pattern):
            try: result[str(path)]=[path.stat().st_mtime_ns,path.stat().st_size]
            except OSError:pass
    return result

def report_time(text, local_zone=None):
    """Prefer embedded report dates to copy/touch-sensitive filesystem timestamps."""
    try:
        header=json.loads(text.splitlines()[0]);value=header.get('timestamp')
        if value:
            stamp=datetime.datetime.fromisoformat(re.sub(r'\s+([+-]\d{2}:?\d{2})$',r'\1',value))
            if stamp.tzinfo:return stamp.timestamp(),'embedded_timestamp'
    except (ValueError,TypeError,IndexError,AttributeError):pass
    match=re.search(r'^Date/Time:\s*(.+?)\s*$',text,re.M)
    if match:
        for pattern in ('%Y-%m-%d %H:%M:%S.%f %z','%Y-%m-%d %H:%M:%S %z',
                        '%a %b %d %H:%M:%S %Y'):
            try:stamp=datetime.datetime.strptime(match[1],pattern)
            except ValueError:continue
            if stamp.tzinfo:return stamp.timestamp(),'embedded_date_with_timezone'
            stamp=stamp.replace(tzinfo=local_zone) if local_zone else stamp.astimezone()
            return stamp.timestamp(),'embedded_local_time_inference'
    return None,'unavailable'

def report_provenance(reports, boot_epoch):
    rows=[]
    for name,(mtime_ns,size) in reports.items():
        try:
            with Path(name).open(errors='replace') as handle:head=handle.read(65536)
            when,source=report_time(head)
        except OSError:when,source=None,'unreadable'
        current=(when>=boot_epoch) if when is not None else mtime_ns>=boot_epoch*1000000000
        rows.append({'path':name,'reported_epoch':when,'time_source':source,
                     'mtime_ns':mtime_ns,'size':size,'current_boot_or_unresolved':current})
    return rows

def gpu_events(out, name):
    return save_command(out,name,['/usr/bin/log','show','--last','boot','--style','compact','--info',
        '--predicate','process == "kernel" AND (eventMessage CONTAINS "GPURestartBegin" OR eventMessage CONTAINS "GPU hang:")'])

def opencore_log_evidence(text, boot_epoch):
    """Keep retained failures separate unless embedded time fits this boot.

    FAT mtimes can have a timezone offset or change during copying. Embedded
    boot.efi time is still a timing inference, not an independent boot identity.
    None means current-boot failure evidence is unavailable, not a clean log.
    """
    text=text.replace('\x00','')
    failures=[line.strip() for line in text.splitlines() if 'Prelinked injection' in line
        and any(value in line for value in ('Invalid Parameter','Not Found','Failed'))]
    result={'boot_provenance':'Unverified: latest file is not proof it belongs to this boot',
            'classification':'unattributed','current_boot_injection_failures':None,
            'retained_file_injection_failures':failures}
    match=re.search(r'\[EB\|LOG:INIT\] (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})',text)
    if not match:return result
    try:
        init=datetime.datetime.fromisoformat(match[1]).replace(tzinfo=datetime.timezone.utc).timestamp()
    except ValueError:return result
    difference=boot_epoch-init
    fits=0<=difference<=180
    result.update(embedded_boot_efi_init=match[1],
        UTC_interpretation_seconds_before_kernel_boot=difference,
        UTC_timing_consistent_with_current_boot=fits,
        classification='current_boot_timing_candidate' if fits else 'outside_current_boot_timing_window',
        boot_provenance='Timing inference from embedded boot.efi INIT interpreted as UTC; file mtime alone is insufficient',
        current_boot_injection_failures=failures if fits else None)
    return result

def video_exercises(mode):
    """Exercise allowed hardware codecs and actual automatic software fallback."""
    if mode not in ('-NRedVDA','-NRedAVC','-NRedAVCEncode'):return []
    decode=('--decode-hevc' if mode=='-NRedVDA' else '--decode-hevc-fallback')
    encode=('--encode-hevc-fallback' if mode=='-NRedAVC' else '--encode-hevc')
    return [('h264-decode','video_probe','--decode-h264'),
            ('hevc-decode' if mode=='-NRedVDA' else 'hevc-decode-fallback','video_probe',decode),
            ('h264-encode','video_probe','--encode-h264'),
            ('hevc-encode-fallback' if mode=='-NRedAVC' else 'hevc-encode','video_probe',encode)]

def deployment_video_profile_matches(deployment, mode, props):
    required=deployment.get('required_video_mode')
    return (not required or mode==required) and all(
        props.get(key)==value for key,value in deployment.get('expected_video_properties',{}).items())

def validate_video_cache(snapshot, arrays, major):
    """Compare all actual VA pages, including feedback consumers and source pitch."""
    if major!=24 or snapshot.get('cache_uuid_hex')!='42ec2890bc40317ebb2745142bff7f26':
        return {'supported_video_reference':False}
    from gen_vda_va_data import parse_header
    text=(ROOT/'NootedRed/VDAVADataSequoia.hpp').read_text()
    references,records=parse_header(text)
    image_base=int(re.search(r'ImageBase = (0x[0-9A-Fa-f]+)',text)[1],16)
    offsets=[int(value,16) for value in re.findall(r'// Page \d+:.*?image offset 0x([0-9A-Fa-f]+)',text)]
    if len(offsets)!=8 or len(records)!=9:return {'reference_table_consistent':False}
    expected={}
    for index,offset in enumerate(offsets):
        name=f'Page{index}';page=bytearray(references[name])
        for record in records:
            if record['page']!=name:continue
            find=references[record['find']];replace=references[record['replace']]
            positions=[m.start() for m in re.finditer(re.escape(find),page)]
            chosen=positions[record['skip']:record['skip']+record['count']]
            if len(chosen)!=record['count']:return {'reference_table_consistent':False}
            for position in chosen:page[position:position+len(find)]=replace
        expected[hex(image_base+offset-0x7ff800000000)]=bytes(page)
    pitch=bytearray(arrays['kVAEncodePitchPage_Sequoia'])
    if pitch[0xaf5:0xaf5+37]!=arrays['kVAEncodePitchFind']:return {'reference_pitch_consistent':False}
    pitch[0xaf5:0xaf5+37]=arrays['kVAEncodePitchReplace'];expected['0x30864c000']=bytes(pitch)
    observed=snapshot.get('video_pages',{})
    return {'supported_video_reference':True,**{f'VA_page_{key}_matches':observed.get(key)==value.hex() for key,value in expected.items()}}

def validate_cache(snapshot, arrays, major):
    if major not in (23,24,25): return {'supported_reference':False}
    ref = arrays['kMTLControlPage_'+{23:'Sonoma',24:'Sequoia',25:'Tahoe'}[major]]
    expected = bytearray(ref)
    sequoia24H232 = major==24 and snapshot.get('cache_uuid_hex')=='90db0deb23443601b011b87312d74cfb'
    if sequoia24H232:
        if expected[0x92c]!=0xd0:return {'reference_table_consistent':False}
        expected[0x92c]=0xc8
    gate = {23:0x1bc,24:0x164,25:0x708}[major]
    expected[gate:gate+2] = bytes.fromhex('eb00' if major==25 else 'eb0b')
    if major==25:
        hits = [m.start() for m in re.finditer(re.escape(bytes.fromhex('0f94c1')),ref)]
        expected[hits[1]:hits[1]+3] = bytes.fromhex('31c990')
    header=(ROOT/'NootedRed/UserSubmitGuard.hpp').read_text()
    payload=bytearray(int(x,16) for x in re.findall(r'0x([0-9a-fA-F]{2})',
        re.search(r'UInt8 Payload\[\] = \{(.*?)\};',header,re.S)[1]))
    method = snapshot.get('submit_guard_method_address',0)
    target = snapshot.get('submit_guard_target',0)
    struct.pack_into('<Q',payload,296,method+15)
    entry = bytes.fromhex('ff2500000000') + struct.pack('<Q',target) + bytes.fromhex('90')
    identities={23:'4c1441fd8a543dc2863d49110b946a25',24:'42ec2890bc40317ebb2745142bff7f26',
                25:'3137475689b434e8a34f56c5d57216a1'}
    return {'supported_reference':True,
            'shared_cache_UUID_matches':snapshot.get('cache_uuid_hex')==identities[major] or sequoia24H232,
            'LegacyBlend_complete_page_matches':snapshot.get('metal_page_hex')==expected.hex(),
            'SubmitGuard_entry_matches':target>0 and snapshot.get('submit_guard_entry_hex')==entry.hex(),
            'SubmitGuard_payload_matches':target>0 and snapshot.get('submit_guard_payload_hex')==payload.hex(),
            'SubmitGuard_payload_RX':snapshot.get('submit_guard_payload_protection')==5}

def embedded_signature_command(header, file_size):
    if len(header)<32:raise ValueError('Truncated Mach-O header')
    magic,cpu,_,_,count,commands_size,_,_=struct.unpack_from('<IiiIIIII',header)
    if magic!=0xfeedfacf or cpu!=0x1000007:raise ValueError('Expected thin x86_64 Mach-O')
    if not 0<count<=1024 or not 0<commands_size<=1024*1024 or len(header)!=32+commands_size:
        raise ValueError('Invalid Mach-O load-command bounds')
    offset=32; signature=None
    for _ in range(count):
        if offset+8>len(header):raise ValueError('Truncated load command')
        command,size=struct.unpack_from('<II',header,offset)
        if size<8 or offset+size>len(header):raise ValueError('Invalid load-command size')
        if command==0x1d:
            if size<16 or signature is not None:raise ValueError('Invalid code-signature command')
            signature=struct.unpack_from('<II',header,offset+8)
        offset+=size
    if offset!=len(header) or signature is None:raise ValueError('Missing or inconsistent embedded signature')
    start,size=signature
    if size<12 or start<32+commands_size or start+size>file_size:
        raise ValueError('Embedded signature outside the file')
    return signature

def register_gl_signature(fd):
    # mmap alone does not attach the driver's signing blob. Use the same existing-file
    # signature registration as dyld, without loading its initializers or calling GL.
    header=os.pread(fd,32,0)
    if len(header)!=32:raise ValueError('Truncated GL driver header')
    commands_size=struct.unpack_from('<I',header,20)[0]
    if commands_size>1024*1024:raise ValueError('Excessive GL driver load commands')
    header+=os.pread(fd,commands_size,32)
    offset,size=embedded_signature_command(header,os.fstat(fd).st_size)
    blob_header=os.pread(fd,12,offset)
    if len(blob_header)!=12:raise ValueError('Truncated embedded signature')
    magic,length,_=struct.unpack('>III',blob_header)
    if magic!=0xfade0cc0 or not 12<=length<=size:raise ValueError('Invalid embedded signature superblob')
    class FileSignatures(ctypes.Structure):
        _fields_=[('file_start',ctypes.c_int64),('blob_start',ctypes.c_void_p),('blob_size',ctypes.c_size_t),
                  ('struct_size',ctypes.c_size_t),('cdhash',ctypes.c_char*20),('hash_type',ctypes.c_int)]
    signature=FileSignatures(0,offset,size,0,b'',0)
    libc=ctypes.CDLL(None,use_errno=True)
    libc.fcntl.restype=ctypes.c_int
    libc.fcntl.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.POINTER(FileSignatures)]
    # F_ADDFILESIGS_RETURN from the macOS SDK; fs_blob_start is a file offset here.
    result=libc.fcntl(fd,97,ctypes.byref(signature))
    if result<0:
        error=ctypes.get_errno();raise OSError(error,os.strerror(error))
    return {'registered_existing_embedded_signature':True,'signed_coverage':signature.file_start,
            'signature_file_offset':offset,'signature_size':size,'GPU_work_submitted':False}

def deployment_gl_profile_matches(deployment, props):
    revision=deployment.get('required_page_local_GL_revision')
    if revision is None:return True
    return (props.get('NRedOpenGLRevision')==revision and props.get('NRedOpenGLPageLocal')==1
            and props.get('NRedOpenGLEnabled')==1 and props.get('NRedOpenGLBackends') in (1,3))

def expected_gl_pages(arrays, major, device_id=None):
    """Full-page references for either legacy or conditional GL builds; no GPU work."""
    family={23:'Sonoma',24:'Sequoia',25:'Tahoe'}.get(major)
    if not family:return []
    result=[]
    if device_id is not None:
        generated=load_arrays(ROOT/'NootedRed/UserOpenGLData.hpp')
        profiles=json.loads((ROOT/'tools/fixtures/opengl-compat.json').read_text())['profiles']
        profile=next(x for x in profiles if x['major']==major)
        for kind,(offset,key,position) in enumerate([
            (0xe000,'Hw',profile['hw']['tailOffset']),
            (0x8000,'Dual',profile['dual']['offset'])]):
            stock=generated[f'Page{major}_{kind}'];target=bytearray(stock)
            payload=generated[f'OS{major}PCI{device_id:04X}{key}']
            target[position:position+len(payload)]=payload
            assert len(target)==4096
            result.append((offset,stock,bytes(target)))
    else:
        for offset,stem,find,replace,skip in [
            (0xe000,'HwInfo','c7477804000000','c7477801000000',0),
            (0x8000,'DualQuad','83e0fe','83c801',1)]:
            stock=arrays[f'kGLDriver{stem}Page_{family}'];target=bytearray(stock)
            sites=[m.start() for m in re.finditer(re.escape(bytes.fromhex(find)),stock)]
            site=sites[skip];target[site:site+len(bytes.fromhex(find))]=bytes.fromhex(replace)
            result.append((offset,stock,bytes(target)))
    if major==24:
        stock=arrays['kGLDriverBudgetPage_Sequoia'];target=bytearray(stock)
        find=arrays['kGLDriverBudgetFind'];site=stock.index(find)
        target[site:site+len(find)]=arrays['kGLDriverBudgetReplace']
        result.append((0x5000,stock,bytes(target)))
    return result

def gl_pages(arrays, major, registration=None, device_id=None):
    references=expected_gl_pages(arrays,major,device_id)
    if not references:return []
    path=Path('/System/Library/Extensions/AMDRadeonX5000GLDriver.bundle/Contents/MacOS/AMDRadeonX5000GLDriver')
    rows=[]
    fd=os.open(path,os.O_RDONLY)
    try:
        status=register_gl_signature(fd)
        if registration is not None:registration.update(status)
        for offset,stock,target in references:
            with mmap.mmap(fd,4096,flags=mmap.MAP_PRIVATE,prot=mmap.PROT_READ|mmap.PROT_EXEC,offset=offset) as m:
                observed=m[:]
            rows.append({'offset':hex(offset),'patched_page_matches':observed==target,'stock_page_matches':observed==stock,
                         'policy':'conditional-device' if device_id is not None else 'legacy'})
    finally:os.close(fd)
    return rows

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path)
    parser.add_argument('--exercise-video',action='store_true')
    parser.add_argument('--exercise-metal',action='store_true')
    metal_mode=parser.add_mutually_exclusive_group()
    metal_mode.add_argument('--metal-render-only',action='store_true',help='with --exercise-metal, defer compute')
    metal_mode.add_argument('--metal-compute-only',action='store_true',help='with --exercise-metal, defer rendering')
    parser.add_argument('--exercise-gl',action='store_true')
    parser.add_argument('--trace-gl-api',action='store_true',help='observe only the GL probe with the deployment-recorded API library; requires --exercise-gl')
    parser.add_argument('--require-vm-trace',action='store_true',help='require all guarded native mapping trace hooks before a GPU exercise')
    parser.add_argument('--require-vm-trace-version',type=int,choices=(1,2),default=1)
    parser.add_argument('--deployment',type=Path,help='require the UUID/hashes recorded in the staged deployment')
    parser.add_argument('--efi-root',type=Path,help='EFI directory whose volume holds OpenCore file logs; does not prove the running bootloader source')
    a=parser.parse_args()
    if a.trace_gl_api and not a.exercise_gl:parser.error('--trace-gl-api requires --exercise-gl')
    now=datetime.datetime.now().astimezone()
    out=(a.out or ROOT/'build'/('feature-check-'+now.strftime('%Y%m%d-%H%M%S'))).resolve()
    out.mkdir(parents=True,mode=0o700,exist_ok=True)
    args=save_command(out,'boot-args',['sysctl','-n','kern.bootargs'])['stdout'].strip().split()
    boot=save_command(out,'boot-time',['sysctl','-n','kern.boottime'])['stdout']
    epoch=int(re.search(r'sec = (\d+)',boot)[1])
    boot_uuid=parse_boot_session(save_command(out,'boot-session',['sysctl','-n','kern.bootsessionuuid']))
    loaded=save_command(out,'loaded-kexts',['/usr/sbin/kextstat','-l'])['stdout']
    row=next((x for x in loaded.splitlines() if 'org.ChefKiss.NootedRed ' in x),'')
    match=re.search(r'\b[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}\b',row)
    uuid=match[0] if match else None
    darwin=command(['uname','-r'])['stdout'].strip();major=int(darwin.split('.')[0])
    raw=save_command(out,'IGPU-private',['/usr/sbin/ioreg','-l','-w0','-r','-n','IGPU','-d','1'])
    props=properties(raw['stdout'])
    summary={'captured_at':now.isoformat(),'boot_epoch':epoch,'boot_session_uuid':boot_uuid,'Darwin':darwin,'boot_args':args,
             'loaded_NootedRed_UUID':uuid,'NRed_properties':props,'exercises':[],
             'GLFix_requested':'-NRedGLFix' in args and '-NRedGLFixOff' not in args,
             'SubmitGuard_opted_out':'-NRedNoSubmitGuard' in args,
             'video_mode':next((x for x in ('-NRedAVC','-NRedAVCEncode','-NRedVDA') if x in args),None),
             'GfxOff_hold_requested':'-NRedVCNNoGfxOff' in args}
    summary['VM_trace_requested']='-NRedVMTrace' in args
    summary['VM_trace_version']=props.get('NRedVMTraceVersion',1) if summary['VM_trace_requested'] else None
    summary['VM_trace_ready']=vm_trace_ready(props,args,a.require_vm_trace_version)
    arrays=load_arrays(ROOT/'NootedRed/UserPatches.cpp')
    try:
        summary['GL_signature_registration']={}
        summary['GL_pages']=gl_pages(arrays,major,summary['GL_signature_registration'],
            props.get('NRedCompatDeviceID',0) if props.get('NRedOpenGLPageLocal')==1 else None)
    except Exception as e:summary['GL_page_error']=str(e)
    before=gpu_events(out,'GPU-events-before')
    baseline_count=before['stdout'].count('GPURestartBegin')
    reports_before=gpu_reports()
    summary['GPU_restart_begin_before']=baseline_count
    summary['GPU_log_query_status_before']=before['returncode']
    deployment_ok=True
    profile_ok=True
    d={}
    if a.deployment:
        d=json.loads(a.deployment.read_text())
        expected_uuid=d.get('release_UUID') or d.get('debug_UUID')
        deployment_ok=bool(expected_uuid) and uuid==expected_uuid
        summary['expected_deployed_UUID_loaded']=deployment_ok
        if d.get('debug_UUID'):summary['expected_debug_UUID_loaded']=deployment_ok
        for name,expected in d.get('probe_sha256',{}).items():
            path=ROOT/'build/tools'/name
            deployment_ok=deployment_ok and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==expected
        summary['deployment_and_probe_identity_verified']=deployment_ok
        profile_ok=deployment_video_profile_matches(d,summary['video_mode'],props)
        summary['expected_video_profile_active']=profile_ok
        gl_profile_ok=deployment_gl_profile_matches(d,props)
        summary['expected_GL_profile_active']=gl_profile_ok
        profile_ok=profile_ok and gl_profile_ok
    if deployment_ok and (ROOT/'build/tools/video_probe').exists():
        snapshot=save_command(out,'cache-only-probe',[str(ROOT/'build/tools/video_probe'),'--cache-only'])
        try:
            capture=json.loads(snapshot['stdout'])
            summary['cache_patch_validation']=validate_cache(capture.get('cache_patch_snapshot',{}),arrays,major)
            summary['video_patch_validation']=validate_video_cache(capture.get('cache_patch_snapshot',{}),arrays,major)
        except (ValueError,KeyError):summary['cache_probe_error']=snapshot
    summary['cache_patch_bytes_verified']=all(summary.get('cache_patch_validation',{'missing':False}).values())
    summary['video_patch_bytes_verified']=all(summary.get('video_patch_validation',{'missing':False}).values())
    summary['GPU_or_WindowServer_report_provenance']=report_provenance(reports_before,epoch)
    summary['existing_GPU_or_WindowServer_reports_this_boot']=[row['path'] for row in summary['GPU_or_WindowServer_report_provenance'] if row['current_boot_or_unresolved']]
    summary['GPU_hang_observed_before']='GPU hang:' in before['stdout']
    # A page-cache read is an observation at that instant. Recheck after the native loader snapshot.
    summary['GL_pages_initial']=summary.get('GL_pages',[])
    try: summary['GL_pages']=gl_pages(arrays,major,summary['GL_signature_registration'],
            props.get('NRedCompatDeviceID',0) if props.get('NRedOpenGLPageLocal')==1 else None)
    except Exception as error: summary['GL_page_error']=str(error)
    ready=all(props.get(k)==1 for k in ['NRedVCNX5000ABIValidated','NRedVCNX6000ABIValidated',
              'NRedVCNNativeLoadReady','NRedVCNEngineAllocated','NRedVDAMediaEnabled'])
    summary['VCN_bridge_ready']=ready
    gl_trace_prefix=None
    if a.trace_gl_api:
        try:
            gl_trace_prefix=traced_gl_command([],out/'GL-api-trace',d.get('gl_api_trace'))
            summary['GL_API_trace']={'library':d['gl_api_trace']['library'],
                'sha256':d['gl_api_trace']['sha256'],'directory':'GL-api-trace',
                'scope':'GL probe process only; read-only snapshots can affect timing'}
        except (OSError,KeyError,ValueError) as error:summary['GL_API_trace_error']=str(error)
    if a.exercise_metal or a.exercise_video or a.exercise_gl:
        if not boot_uuid:
            summary['exercise_blocked']='Cannot establish boot-session identity; no GPU work submitted'
        elif not profile_ok:
            summary['exercise_blocked']='The staged video/GL mode or properties are not active; no GPU work submitted'
        elif a.trace_gl_api and gl_trace_prefix is None:
            summary['exercise_blocked']='GL API observer identity could not be verified; no GPU work submitted'
        elif (a.require_vm_trace or a.require_vm_trace_version>1) and not summary['VM_trace_ready']:
            summary['exercise_blocked']='Guarded native mapping trace hooks are not ready; no GPU work submitted'
        elif not deployment_ok or props.get('NRedSubmitGuardVersion',0)<2 or '-NRedNoSubmitGuard' in args:
            summary['exercise_blocked']='Updated kext with SubmitGuard v2 must be running; collector performed no GPU work'
        elif not summary['cache_patch_bytes_verified']:
            summary['exercise_blocked']='Actual private cache patch bytes have not been verified; no GPU work submitted'
        elif not summary['GLFix_requested'] or not summary.get('GL_pages') or not all(x['patched_page_matches'] for x in summary['GL_pages']):
            summary['exercise_blocked']='Corrected OpenGL pages are not enabled and verified; no GPU work submitted'
        elif baseline_count or summary['GPU_hang_observed_before'] or summary['existing_GPU_or_WindowServer_reports_this_boot']:
            summary['exercise_blocked']='This boot already has GPU/WindowServer fault evidence; no further GPU work submitted'
        elif before['returncode']!=0:
            summary['exercise_blocked']='Cannot establish GPU reset baseline'
        else:
            cases=[]
            if a.exercise_metal:
                if not a.metal_compute_only: cases += [('metal-render','metal_probe','--render')]
                if not a.metal_render_only: cases += [('metal-compute','metal_probe','--compute')]
            if a.exercise_video:
                if not ready or not summary['video_mode']:
                    summary['video_exercise_blocked']='VCN bridge/video mode is not ready; no hardware pass inferred'
                elif not summary['video_patch_bytes_verified']:
                    summary['video_exercise_blocked']='Actual VA driver patch pages are not verified; no hardware work submitted'
                else:
                    cases += video_exercises(summary['video_mode'])
            if a.exercise_gl:
                if summary['GLFix_requested']:cases += [('GL-render','gl_blend_probe','--render')]
                else:summary['GL_exercise_blocked']='GLFix is not requested'
            for name,tool,mode in cases:
                invocation=[str(ROOT/'build/tools'/tool),mode]
                if tool=='gl_blend_probe':invocation += ['--yes','--timeout','30']
                if tool=='gl_blend_probe' and gl_trace_prefix:
                    (out/'GL-api-trace').mkdir(mode=0o700)
                    invocation=gl_trace_prefix+invocation
                kernel=KernelEvidence(out/(name+'-kernel-ring'))
                if not kernel.start():
                    summary['exercise_blocked']='Cannot capture the kernel ring before submission; no further GPU work submitted'
                    summary['kernel_capture_failure']=kernel.finish()
                    break
                try:
                    result=save_command(out,name,invocation,75 if tool=='video_probe' else 40)
                    # Retain fault data through the delayed report observation as well.
                    time.sleep(10)
                finally:
                    kernel_result=kernel.finish()
                evidence={'name':name,'returncode':result['returncode'],'passed':False}
                evidence['kernel_ring_capture']={'directory':name+'-kernel-ring',
                    'samples_saved':len(kernel_result['samples']),'error':kernel_result['error']}
                try:
                    parsed=json.loads(result['stdout']);(out/(name+'.json')).write_text(json.dumps(parsed,indent=2)+'\n')
                    evidence['functional_output_passed']=parsed.get('passed',False)
                    evidence['cache_patch_validation']=validate_cache(parsed.get('cache_patch_snapshot',{}),arrays,major)
                    checks=evidence['cache_patch_validation']
                    evidence['passed']=result['returncode']==0 and parsed.get('passed',False) and all(checks.values())
                    if tool=='video_probe':
                        evidence['video_patch_validation']=validate_video_cache(parsed.get('cache_patch_snapshot',{}),arrays,major)
                        evidence['passed']=evidence['passed'] and all(evidence['video_patch_validation'].values())
                except (ValueError,KeyError):
                    evidence['passed']=tool=='gl_blend_probe' and result['returncode']==0 and 'SKIP' not in result['stdout']
                if tool=='gl_blend_probe' and gl_trace_prefix:
                    logs=list((out/'GL-api-trace').glob('api-*.log'))
                    buffers=list((out/'GL-api-trace').glob('buffers-*.bin'))
                    evidence['API_trace_capture']={'loaded_in_probe':any(re.search(
                        r'^loaded pid=\d+ name=gl_blend_probe$',p.read_text(errors='replace'),re.M) for p in logs),
                        'buffer_bytes':sum(p.stat().st_size for p in buffers)}
                    evidence['passed']=evidence['passed'] and evidence['API_trace_capture']['loaded_in_probe']
                summary['exercises'].append(evidence)
                # GPU timeout/restart reports may arrive after a command reports completion.
                current=gpu_events(out,name+'-GPU-events')
                new_reports=[key for key,value in gpu_reports().items() if reports_before.get(key)!=value]
                evidence['new_GPU_or_WindowServer_reports']=new_reports
                if kernel_result['error'] or not evidence['passed'] or new_reports or current['returncode']!=0 or 'GPU hang:' in current['stdout'] or current['stdout'].count('GPURestartBegin')>baseline_count or result['returncode']<0 or result['returncode']==124:
                    summary['stopped_after']=name
                    summary['stop_reason']='Failed functional/patch check, GPU/WindowServer report, reset, unavailable log, signal or timeout; remaining workloads not submitted'
                    break
    if raw['returncode']==0:
        post=save_command(out,'IGPU-after-private',['/usr/sbin/ioreg','-l','-w0','-r','-n','IGPU','-d','1'])
        summary['NRed_properties_after']=properties(post['stdout'])
    else:
        summary['IORegistry_capture_error']=raw
    final=gpu_events(out,'GPU-events-after')
    summary['new_GPU_or_WindowServer_reports']=[key for key,value in gpu_reports().items() if reports_before.get(key)!=value]
    summary['GPU_log_query_status_after']=final['returncode']
    summary['GPU_restart_begin_after']=final['stdout'].count('GPURestartBegin')
    summary['GPU_hang_observed_after']='GPU hang:' in final['stdout']
    summary['new_GPU_restart_begin_entries']=(summary['GPU_restart_begin_after']-baseline_count) if final['returncode']==before['returncode']==0 else None
    dmesg=save_command(out,'dmesg',['sudo','-n','/sbin/dmesg'])
    summary['dmesg_capture_status']=dmesg['returncode']
    summary['dmesg_captured']=dmesg['returncode']==0 and bool(dmesg['stdout'])
    summary['retained_dmesg_allocation_failure_lines']=dmesg['stdout'].count('Failed to allocate size:')
    summary['retained_dmesg_resolver_unmatched_lines']=dmesg['stdout'].count('still unmatched for signature')
    def kernel_chunks():
        yield dmesg['stdout']
        for path in sorted(out.glob('*-kernel-ring/dmesg-*.txt')):
            yield path.read_text(errors='replace')
    trace=vm_trace_events(kernel_chunks())
    (out/'VM-trace-events.json').write_text(json.dumps(trace,indent=2)+'\n')
    summary['VM_trace_complete_operations']=trace['complete_operations']
    summary['VM_trace_native_false_results']=len(trace['native_false_results'])
    details=vm_mapping_details(kernel_chunks())
    (out/'VM-mapping-details.json').write_text(json.dumps(details,indent=2)+'\n')
    summary['VM_trace_complete_ranges']=details['complete_ranges']
    summary['VM_trace_constructor_outputs']=len(details['constructed_entries'])
    checked=save_command(out,'NotificationCenter-code',[sys.executable,str(ROOT/'tools/check_notification_code.py')])
    try: summary['NotificationCenter_code_validation']=json.loads(checked['stdout'])
    except ValueError:summary['NotificationCenter_code_validation_error']=checked['stderr']
    save_command(out,'NotificationCenter-CPU',['/bin/ps','-ww','-axo','pid,comm,%cpu,time'])
    report=Path.home()/'Desktop/Zen-about-support.txt'
    fresh=report.exists() and report.stat().st_mtime>=epoch
    summary['Zen_support_export_fresh']=fresh
    if fresh:
        text=report.read_text(errors='replace');m=re.search(r'^Compositing:\s*(.*)$',text,re.M)
        summary['Zen_compositing']=m[1] if m else None
    efi_root=a.efi_root or (Path(d['config_path']).parent.parent if d.get('config_path') else Path('/Volumes/OPENCORE/EFI'))
    summary['EFI_root_for_log_lookup']=str(efi_root)
    logs=sorted(efi_root.parent.glob('opencore-*.txt'),key=lambda p:p.stat().st_mtime,reverse=True)
    if logs:
        log=logs[0];(out/'OpenCore-latest-private.txt').write_bytes(log.read_bytes())
        evidence=opencore_log_evidence(log.read_text(errors='replace'),epoch)
        summary['latest_OpenCore_log']={'name':log.name,'mtime':log.stat().st_mtime,'mtime_after_boot':log.stat().st_mtime>=epoch,
                                     **{k:v for k,v in evidence.items() if not k.endswith('injection_failures')}}
        summary['OpenCore_injection_failures']=evidence['current_boot_injection_failures']
        summary['retained_OpenCore_log_injection_failures']=evidence['retained_file_injection_failures']
    else:
        summary['OpenCore_injection_failures']=None
        summary['latest_OpenCore_log']={'classification':'unavailable',
            'boot_provenance':'No retained file log; current-boot OpenCore injection status is unavailable'}

    sleep_stats=save_command(out,'sleep-stats',['/usr/bin/pmset','-g','stats'])
    sleep_log=save_command(out,'sleep-log-private',['/usr/bin/pmset','-g','log'])
    save_command(out,'power-assertions-private',['/usr/bin/pmset','-g','assertions'])
    if sleep_stats['returncode']==sleep_log['returncode']==0:
        summary['sleep_wake_evidence']=sleep_evidence(sleep_stats['stdout'],sleep_log['stdout'],epoch,time.time())
    else:
        summary['sleep_wake_evidence']={'system_sleep_cycle_recorded':False,'functional_wake_verified':False,
            'capture_error':{'stats_returncode':sleep_stats['returncode'],'log_returncode':sleep_log['returncode']}}

    final_boot_uuid=parse_boot_session(save_command(out,'boot-session-after',['sysctl','-n','kern.bootsessionuuid']))
    summary['boot_session_uuid_after']=final_boot_uuid
    summary['boot_session_continuity_verified']=bool(boot_uuid) and boot_uuid==final_boot_uuid
    summary['all_requested_exercises_passed']=summary['boot_session_continuity_verified'] and summary.get('NotificationCenter_code_validation',{}).get('all_code_pages_match',False) and bool(summary['exercises']) and all(x['passed'] for x in summary['exercises']) and not any(k in summary for k in ['exercise_blocked','video_exercise_blocked','GL_exercise_blocked','stopped_after']) and summary['new_GPU_restart_begin_entries']==0 and not summary['GPU_hang_observed_after'] and not summary['new_GPU_or_WindowServer_reports']
    summary['GPU_work_submitted']=bool(summary['exercises'])
    summary['rendering_patch_installation_verified']=deployment_ok and summary.get('expected_GL_profile_active',True) and props.get('NRedSubmitGuardVersion',0)>=2 and props.get('NRedLegacyBlendVersion',0)>=2 and props.get('NRedSubmitGuardWindowServerApplied')==1 and props.get('NRedLegacyBlendWindowServerApplied')==1 and all(summary.get('cache_patch_validation',{'missing':False}).values()) and bool(summary.get('GL_pages')) and all(x['patched_page_matches'] for x in summary.get('GL_pages',[])) and summary.get('NotificationCenter_code_validation',{}).get('all_code_pages_match',False)
    summary['interpretation']='Patch application, functional output and system stability are separate checks. No claim of all release features working is inferred from properties alone.'
    (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2));print('Saved:',out)
    if (a.require_vm_trace or a.require_vm_trace_version>1) and not summary['VM_trace_ready']:return 1
    if a.deployment and not summary['rendering_patch_installation_verified']:return 1
    if a.deployment and not summary['boot_session_continuity_verified']:return 1
    if a.deployment and not profile_ok:return 1
    if a.deployment and d.get('required_VA_pages') and not summary['video_patch_bytes_verified']:return 1
    if (a.exercise_metal or a.exercise_video or a.exercise_gl) and not summary['all_requested_exercises_passed']:return 1
    return 0

if __name__=='__main__':sys.exit(main())
