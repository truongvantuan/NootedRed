#!/usr/bin/env python3
"""Make diagnostic single-item HEIF variants without decoding or altering coded data.

Only supports direct hvc1 images with 16-bit item IDs. Keeps every box size and
file offset intact: changes pitm, hides iref, and clears auxC associations.
The resulting file is a test input, never a replacement for the original asset.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from inspect_heif import boxes, inspect, require


def isolate(data, item):
    metadata = inspect(data)
    require(item in metadata['items'] and metadata['items'][item]['type'] == 'hvc1',
            'isolation requires a direct hvc1 item')
    require(any(p['type'] == 'hvcC' for p in metadata['items'][item].get('properties', [])),
            'missing associated codec configuration')
    result = bytearray(data)
    edits = []
    for kind, a, b, _ in boxes(data):
        if kind != b'meta':
            continue
        for kind, a, b, offset in boxes(data, a + 4, b):
            if kind == b'pitm':
                require(data[a] == 0 and item <= 65535, 'unsupported primary ID version')
                result[a+4:a+6] = struct.pack('>H', item)
                edits.append({'kind': 'primary_item', 'offset': a+4, 'item': item})
            elif kind == b'iref':
                result[offset+4:offset+8] = b'free'
                edits.append({'kind': 'hide_item_references', 'offset': offset+4})
            elif kind == b'iprp':
                for typ, x, y, _ in boxes(data, a, b):
                    if typ != b'ipma':
                        continue
                    require(data[x] == 0, 'unsupported association ID version')
                    wide = bool(int.from_bytes(data[x+1:x+4], 'big') & 1)
                    width = 2 if wide else 1
                    mask = 0x7fff if wide else 0x7f
                    count = int.from_bytes(data[x+4:x+8], 'big')
                    pos = x+8
                    for _ in range(count):
                        require(pos+3 <= y, 'truncated item associations')
                        pos += 2
                        n = data[pos]
                        pos += 1
                        for _ in range(n):
                            require(pos+width <= y, 'truncated property association')
                            index = int.from_bytes(data[pos:pos+width], 'big') & mask
                            if index and metadata['properties'][index-1]['type'] == 'auxC':
                                result[pos:pos+width] = bytes(width)
                                edits.append({'kind': 'clear_auxiliary_property', 'offset': pos})
                            pos += width
                    require(pos == y, 'association length mismatch')
    verified = inspect(result)
    require(verified['primary_item'] == item and not verified['references'], 'isolation failed')
    # All edits are inside metadata. iloc extents and every byte of mdat remain intact.
    for kind, a, b, _ in boxes(data):
        if kind == b'mdat':
            require(result[a:b] == data[a:b], 'coded payload changed')
    return bytes(result), edits


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input', type=Path)
    ap.add_argument('output', type=Path)
    ap.add_argument('--item', type=int, required=True)
    args = ap.parse_args()
    require(args.input.resolve() != args.output.resolve(), 'refusing to overwrite source')
    require(args.input.stat().st_size <= 32*1024*1024, 'input too large')
    source = args.input.read_bytes()
    output, edits = isolate(source, args.item)
    # Exclusive creation preserves an existing diagnostic input too.
    with args.output.open('xb') as handle:
        handle.write(output)
    print(json.dumps({'source_sha256': hashlib.sha256(source).hexdigest(),
                      'output_sha256': hashlib.sha256(output).hexdigest(),
                      'item': args.item, 'edits': edits,
                      'coded_payload_unchanged': True, 'GPU_work_submitted': False}, indent=2))


if __name__ == '__main__':
    main()
