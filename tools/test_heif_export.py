#!/usr/bin/env python3
"""Exercise real item-extent/NAL extraction on synthetic HEIF, without decoding."""
import base64
import struct
from export_heif_item import export
from inspect_heif import InvalidHEIF
from test_heif_inspection import box, config


def fixture(reference=0, offset_delta=0, nal_size=2):
    nals = [bytes([typ << 1, 1]) for typ in (32,33,34)]
    codec = bytearray(config(1,1));codec[22]=3
    for typ, nal in zip((32,33,34),nals):
        codec += bytes([typ])+struct.pack('>HH',1,len(nal))+nal
    header = box(b'ftyp',b'heic'+bytes(4)+b'mif1')
    packet = struct.pack('>I',nal_size)+b'\x26\x01'
    def meta(offset):
        info=box(b'infe',b'\x02\0\0\0'+struct.pack('>HH4s',1,0,b'hvc1')+b'\0')
        loc=bytes(4)+b'\x44\0'+struct.pack('>HHHHII',1,1,reference,1,offset+offset_delta,len(packet))
        assoc=bytes(4)+struct.pack('>IHB',1,1,1)+b'\x01'
        return box(b'meta',bytes(4)+box(b'pitm',bytes(4)+b'\0\x01')+
                   box(b'iinf',bytes(4)+b'\0\x01'+info)+box(b'iloc',loc)+
                   box(b'iprp',box(b'ipco',box(b'hvcC',codec))+box(b'ipma',assoc)))
    metadata=meta(0)
    return header+meta(len(header)+len(metadata)+8)+box(b'mdat',packet),nals,packet


def reject(data):
    try:export(data,1)
    except InvalidHEIF:return
    raise AssertionError('invalid compressed item accepted')


def main():
    data,nals,packet=fixture();result=export(data,1)
    assert base64.b64decode(result['sample_base64'])==packet
    assert [base64.b64decode(x) for x in result['parameter_sets_base64']]==nals
    for i in range(len(data)):reject(data[:i])
    reject(fixture(reference=1)[0]);reject(fixture(offset_delta=10000)[0])
    reject(fixture(nal_size=10000)[0]);reject(fixture(nal_size=1)[0])
    print(f'HEIF extent/NAL export: exact payload and {len(data)+4} invalid/truncated cases passed')


if __name__=='__main__':main()
