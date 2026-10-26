#!/usr/bin/env python3
"""Reject misleading allocation/result associations; no GPU or kernel access."""
from collect_gpu_allocation_trace import parse_trace,ring_messages
from pathlib import Path
import json
import tempfile
allocation='AllocTrace allocation-fail serial=1 tid=8 physical=20 outer=10 pid=0 name= bytes=15728640 align=65536 minBlock=4096 origin=1 operation=2 noFixed=1 caller=0x1234'
physical='AllocTrace physical-end tid=8 physical=20 failedRequests=1 sampled=1 result=0 flags=0x1080000'
paging='AllocTrace pageon-end tid=8 outer=10 failures=1 sampled=1 flagsBefore=0x1 flagsAfter=0x2 options=0x0 caller=0x9999'
trace=parse_trace([allocation,physical,paging,allocation,'AllocTrace backtrace serial=1 frame=0 pc=0x4567'])
assert len(trace['failed_native_requests'])==1 and not trace['conflicting_records']
row=trace['failed_native_requests'][0];assert row['current_process_name']=='' and row['pid']==0
assert row['physical_outcome']['native_result']==0 and row['resource_paging_state']['flags_after']==2
assert 'native_result' not in row['resource_paging_state'] and row['backtrace']==[{'frame':0,'pc':0x4567}]
assert not parse_trace([physical])['failed_native_requests']
assert parse_trace([allocation,physical.replace('tid=8','tid=9')])['incomplete_physical_pairs']==[1]
assert parse_trace([allocation,allocation.replace('bytes=15728640','bytes=8192')])['conflicting_records']
assert parse_trace([allocation,'AllocTrace detail limit reached'])['detail_limit_reached']
assert parse_trace(['AllocTrace allocation-fail serial=1 tid=8 TRUNCATED'])['unparsed_trace_records']
named=parse_trace([allocation.replace('name= bytes','name=Zen GPU Helper bytes')])
assert named['failed_native_requests'][0]['current_process_name']=='Zen GPU Helper'
with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary);feature=root/'feature';feature.mkdir();capture=root/'ring';capture.mkdir()
    (feature/'dmesg.txt').write_text(allocation+'\n'+physical+'\n')
    meta={'boot_session_uuid':'BOOT-A','boot_session_continuity_verified':True,'dmesg_captured':True}
    (feature/'SUMMARY.json').write_text(json.dumps(meta))
    (capture/'trace-private.txt').write_text(allocation+'\n'+paging+'\n')
    ring_meta={'boot_session_uuid':'BOOT-A','same_boot':True,'errors':[],'file':'trace-private.txt'}
    (capture/'SUMMARY.json').write_text(json.dumps(ring_meta))
    messages,sources=ring_messages([feature],[capture],'BOOT-A')
    assert len(messages)==3 and len(sources)==2
    assert parse_trace(messages)['failed_native_requests'][0]['physical_outcome']['native_result']==0
    for field,value in [('boot_session_uuid','BOOT-B'),('same_boot',False),('errors',['dmesg failed']),('file','../feature/dmesg.txt')]:
        (capture/'SUMMARY.json').write_text(json.dumps({**ring_meta,field:value}))
        try:ring_messages([], [capture], 'BOOT-A')
        except ValueError:pass
        else:raise AssertionError('Unverified/misdirected ring capture accepted: '+field)
    (capture/'SUMMARY.json').write_text(json.dumps({**ring_meta,'samples':[{'new_lines':2}],'errors':['sudo ticket expired']}))
    assert len(ring_messages([], [capture], 'BOOT-A', allow_partial=True)[0])==2
    for update in ({'same_boot':False},{'boot_session_uuid':'BOOT-B'},{'samples':[]}):
        (capture/'SUMMARY.json').write_text(json.dumps({**ring_meta,'samples':[{}],'errors':['failed'],**update}))
        try:ring_messages([], [capture], 'BOOT-A', allow_partial=True)
        except ValueError:pass
        else:raise AssertionError('Partial mode accepted unverified provenance')
    for field,value in [('boot_session_uuid','BOOT-B'),('boot_session_continuity_verified',False),('dmesg_captured',False)]:
        (feature/'SUMMARY.json').write_text(json.dumps({**meta,field:value}))
        try:ring_messages([feature], [], 'BOOT-A')
        except ValueError:pass
        else:raise AssertionError('Unverified feature ring accepted: '+field)
print('allocation capture: deduplication, thread/event ownership, kernel-worker identity, void paging semantics, incomplete/conflicting/truncated and capped evidence handled')
print('kernel ring: same-boot provenance, successful capture, deduplication and file containment verified; wrong/missing/error provenance rejected')
