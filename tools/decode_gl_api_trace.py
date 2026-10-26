#!/usr/bin/env python3
"""Decode bounded, explicit GL IB ranges from saved API snapshots; no GPU access.

PM4 packet framing and WRITE_DATA control fields follow AMD's soc15d.h:
https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/soc15d.h
The caller supplies the IB GPU address and length from separate evidence. No
opcode search or guessed stream start is used. Snapshot bytes do not prove GPU
execution, residency, or that a particular packet caused a fault.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

HEADER=struct.Struct('<8Q')
MAX_FILE=8388608
MAX_CAPTURE=131072

class DecodeError(ValueError):
    pass

def snapshots(raw):
    if len(raw)>MAX_FILE:raise DecodeError('Snapshot file exceeds observer byte budget')
    offset=0
    while offset<len(raw):
        if len(raw)-offset<HEADER.size:raise DecodeError('Truncated snapshot header')
        magic,pid,sequence,port,kind,gpu,cpu,size=HEADER.unpack_from(raw,offset)
        if magic!=0x4e524447:raise DecodeError('Unknown snapshot magic')
        if not 0<pid<2**31 or sequence>96 or port>=2**32:
            raise DecodeError('Invalid snapshot process/sequence/port')
        if not 0<size<=MAX_CAPTURE:raise DecodeError('Invalid snapshot size')
        start=offset+HEADER.size;end=start+size
        if end>len(raw):raise DecodeError('Truncated snapshot payload')
        if gpu+size>2**64 or cpu+size>2**64:raise DecodeError('Snapshot address overflow')
        yield {'file_offset':offset,'pid':pid,'sequence':sequence,'port':port,
               'mapping_type':kind,'gpu_address':gpu,'cpu_address':cpu},raw[start:end]
        offset=end

def decode_ib(data):
    if not data or len(data)>MAX_CAPTURE or len(data)%4:
        raise DecodeError('IB length must be nonempty, bounded and dword aligned')
    words=struct.unpack('<'+'I'*(len(data)//4),data)
    index=0;packet_count=0;writes=[]
    while index<len(words):
        header=words[index];kind=header>>30
        if kind==2:
            length=1
        elif kind==3:
            length=((header>>16)&0x3fff)+2
        else:
            raise DecodeError(f'Unsupported packet type {kind} at byte {index*4:#x}; no resynchronization attempted')
        if index+length>len(words):raise DecodeError(f'Truncated packet at byte {index*4:#x}')
        if kind==3 and ((header>>8)&255)==0x37:
            if length<5:raise DecodeError(f'Short WRITE_DATA at byte {index*4:#x}')
            control,low,high=words[index+1:index+4]
            selector=(control>>8)&15
            entry={'byte_offset':hex(index*4),'control':hex(control),'destination_selector':selector,
                   'destination_kind':{0:'register',1:'memory-sync',2:'gl2',3:'gds',5:'memory-async'}.get(selector,'unknown'),
                   'write_one_address':bool(control&(1<<16)),'write_confirm':bool(control&(1<<20)),
                   'data_dwords':length-4,'first_data_words':[hex(w) for w in words[index+4:min(index+length,index+8)]],
                   'raw_address_words':[hex(low),hex(high)]}
            if selector in (1,2,5):
                address=(high<<32)|low
                size=4 if entry['write_one_address'] else (length-4)*4
                if address+size>2**64:raise DecodeError('WRITE_DATA address overflow')
                entry.update({'GPU_destination':hex(address),'destination_aligned':not bool(address&3),
                              'write_span_bytes':size})
            writes.append(entry)
        packet_count+=1;index+=length
    return {'complete':True,'byte_length':len(data),'packet_count':packet_count,'WRITE_DATA':writes}

def analyze(raw,gpu,length,pid=None):
    if not 0<=gpu<2**64 or gpu%4 or not 0<length<=MAX_CAPTURE or length%4 or gpu+length>2**64:
        raise DecodeError('Invalid IB address/length')
    streams={};incomplete=[];records=0
    for metadata,data in snapshots(raw):
        records+=1;base=metadata['gpu_address']
        if not base or (pid is not None and metadata['pid']!=pid) or not base<=gpu<base+len(data):continue
        relative=gpu-base
        if relative+length>len(data):
            incomplete.append(dict(metadata,error='Requested IB extent exceeds captured mapping prefix'))
            continue
        stream=data[relative:relative+length];digest=hashlib.sha256(stream).hexdigest()
        # Retain every record's provenance even when bytes are identical.
        key=(metadata['pid'],digest)
        if key not in streams:
            try:decoded=decode_ib(stream)
            except DecodeError as error:decoded={'complete':False,'error':str(error)}
            streams[key]={'pid':metadata['pid'],'stream_sha256':digest,'decode':decoded,'observations':[]}
        streams[key]['observations'].append(metadata)
    return {'container_sha256':hashlib.sha256(raw).hexdigest(),'records':records,
            'requested_IB':{'GPU_address':hex(gpu),'length':hex(length),'pid':pid},
            'streams':list(streams.values()),'insufficient_captures':incomplete,
            'GPU_work_submitted':False,
            'interpretation':'Explicit IB range only; strict packet boundaries. Saved pre-call snapshots do not prove execution, installed GPU mappings, fault causation, or completeness of other buffers.'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('buffers',type=Path)
    parser.add_argument('--gpu',type=lambda s:int(s,0),required=True)
    parser.add_argument('--length',type=lambda s:int(s,0),required=True)
    parser.add_argument('--pid',type=int)
    parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    try:
        if args.buffers.stat().st_size>MAX_FILE:raise DecodeError('Snapshot file exceeds observer byte budget')
        result=analyze(args.buffers.read_bytes(),args.gpu,args.length,args.pid)
    except (OSError,DecodeError) as error:parser.error(str(error))
    rendered=json.dumps(result,indent=2)+'\n'
    if args.out:args.out.write_text(rendered)
    else:print(rendered,end='')
    return 0 if any(s['decode']['complete'] for s in result['streams']) else 1

if __name__=='__main__':raise SystemExit(main())
