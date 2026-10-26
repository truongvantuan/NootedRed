#!/usr/bin/env python3
"""CPU fixtures rejecting false opcode matches and damaged diagnostic records."""
import struct
from decode_gl_api_trace import snapshots,decode_ib,analyze,DecodeError,HEADER,MAX_FILE,MAX_CAPTURE

def packed(*words):return struct.pack('<'+'I'*len(words),*words)
write=packed(0xc0033700,0x00100100,0x4000,4,0)
result=decode_ib(write)
assert result['packet_count']==1 and result['WRITE_DATA'][0]['GPU_destination']=='0x400004000'
assert result['WRITE_DATA'][0]['destination_kind']=='memory-sync'
# A WRITE_DATA-looking word inside a NOP payload is data, not a second packet.
hidden=packed(0xc0041000,0xc0033700,0x00100100,0x1000,4,0)
assert not decode_ib(hidden)['WRITE_DATA']
combined=decode_ib(packed(0x80000000)+hidden+write)
assert combined['packet_count']==3 and len(combined['WRITE_DATA'])==1
assert combined['WRITE_DATA'][0]['byte_offset']==hex(len(hidden)+4)
assert 'GPU_destination' not in decode_ib(packed(0xc0033700,0,0x4000,4,0))['WRITE_DATA'][0]
assert decode_ib(packed(0xc0043700,0x00110100,0x4000,4,0,1))['WRITE_DATA'][0]['write_span_bytes']==4
assert decode_ib(packed(0xc0043700,0x00100100,0x4000,4,0,1))['WRITE_DATA'][0]['write_span_bytes']==8
for bad in (b'',write[:-1],write[:-4],packed(0x40000000),packed(0),packed(0xc0003700,0),
            packed(0xc0043700,0x100,0xfffffffc,0xffffffff,0,1)):
    try:decode_ib(bad)
    except DecodeError:pass
    else:raise AssertionError('Accepted malformed packet stream')

def record(payload=write,seq=1,gpu=0x400060000):
    return HEADER.pack(0x4e524447,100,seq,42,0x10001,gpu,0x100000000,len(payload))+payload
raw=record(seq=1)+record(seq=2)
assert len(list(snapshots(raw)))==2
decoded=analyze(raw,0x400060000,len(write),100)
assert len(decoded['streams'])==1 and len(decoded['streams'][0]['observations'])==2
assert not analyze(raw,0x400060000,len(write),101)['streams']
assert analyze(raw,0x400060000,len(write)+4)['insufficient_captures']
assert not analyze(record(gpu=0),0,len(write))['streams']
sub=analyze(record(packed(0x80000000)+write),0x400060004,len(write))
assert sub['streams'][0]['decode']['WRITE_DATA'][0]['GPU_destination']=='0x400004000'
for bad in (raw[:10],raw[:-1],b'\0'*64,HEADER.pack(0x4e524447,100,97,42,1,1,1,1)+b'x',
            HEADER.pack(0x4e524447,100,1,42,1,1,1,MAX_CAPTURE+1),b'x'*(MAX_FILE+1)):
    try:list(snapshots(bad))
    except DecodeError:pass
    else:raise AssertionError('Accepted malformed snapshot container')
for address,length in [(0x400060001,4),(0x400060000,0),(0x400060000,MAX_CAPTURE+4),(2**64-4,8)]:
    try:analyze(raw,address,length)
    except DecodeError:pass
    else:raise AssertionError('Accepted invalid IB extent')
print('GL API decoder: explicit ranges, packet boundaries, address spaces, repeated snapshots and malformed capture limits pass; no GPU access')
