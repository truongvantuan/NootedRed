#!/usr/bin/env python3
"""Export one direct HEVC HEIF item for a one-frame VideoToolbox diagnostic.

Reads container metadata and copies compressed bytes only; submits no GPU work.
Rejects external data references, derived items and unsupported extent methods.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
from inspect_heif import boxes, inspect, require


def export(data, item):
    meta = inspect(data)
    require(item in meta['items'] and meta['items'][item]['type'] == 'hvc1', 'not a direct HEVC item')
    props = meta['items'][item].get('properties', [])
    configs = [p for p in props if p['type'] == 'hvcC']
    require(len(configs) == 1, 'missing or ambiguous HEVC configuration')
    config = configs[0]
    top = list(boxes(data))
    _, a, b, _ = next(x for x in top if x[0] == b'meta')
    children = list(boxes(data, a+4, b))
    idat = [x[1] for x in children if x[0] == b'idat']
    extents = []
    found = False
    for kind, a, b, _ in children:
        if kind != b'iloc':
            continue
        p = data[a:b]
        require(len(p) >= 8 and p[0] in (0, 1, 2), 'unsupported iloc')
        version = p[0]
        offset_size, length_size = p[4] >> 4, p[4] & 15
        base_size, index_size = p[5] >> 4, p[5] & 15 if version else 0
        require(all(n in (0, 4, 8) for n in (offset_size, length_size, base_size, index_size)), 'unsupported extent width')
        pos = 6
        def take(n):
            nonlocal pos
            require(pos+n <= len(p), 'truncated item location')
            value = int.from_bytes(p[pos:pos+n], 'big')
            pos += n
            return value
        count = take(4 if version == 2 else 2)
        require(count <= 10000, 'excessive item locations')
        for _ in range(count):
            current = take(4 if version == 2 else 2)
            method = take(2) & 15 if version else 0
            ref = take(2)
            base = take(base_size)
            n = take(2)
            require(n <= 10000, 'excessive extents')
            current_extents = []
            for _ in range(n):
                take(index_size)
                start, size = take(offset_size), take(length_size)
                if current == item:
                    require(ref == 0 and method in (0, 1), 'external or derived item location')
                    require(method != 1 or len(idat) == 1, 'missing idat')
                    start += base + (idat[0] if method == 1 else 0)
                    require(size and start+size <= len(data), 'invalid compressed extent')
                    current_extents.append((start, size))
            if current == item:
                require(not found, 'duplicate item location')
                found = True
                extents = current_extents
        require(pos == len(p), 'trailing item-location bytes')
    require(found and extents, 'no compressed item data')
    sample = b''.join(data[a:a+n] for a, n in extents)
    require(len(sample) <= 32*1024*1024, 'sample too large')
    # Validate every length-prefixed sample NAL before handing it to a decoder.
    length_bytes = config['nal_length_bytes']
    pos = 0
    while pos < len(sample):
        require(pos+length_bytes <= len(sample), 'truncated sample NAL length')
        size = int.from_bytes(sample[pos:pos+length_bytes], 'big')
        pos += length_bytes
        require(size >= 2 and pos+size <= len(sample), 'invalid sample NAL extent')
        pos += size
    _, a, b, _ = next(boxes(data, config['file_offset']))
    payload = data[a:b]
    pos = 23
    parameter_sets = []
    for _ in range(payload[22]):
        typ = payload[pos] & 63
        n = int.from_bytes(payload[pos+1:pos+3], 'big')
        pos += 3
        for _ in range(n):
            size = int.from_bytes(payload[pos:pos+2], 'big')
            pos += 2
            if typ in (32, 33, 34):
                parameter_sets.append(base64.b64encode(payload[pos:pos+size]).decode())
            pos += size
    require(len(parameter_sets) >= 3, 'missing VPS/SPS/PPS')
    return {'schema': 1, 'source_sha256': hashlib.sha256(data).hexdigest(), 'item': item,
            'configuration': config, 'parameter_sets_base64': parameter_sets,
            'sample_base64': base64.b64encode(sample).decode(),
            'sample_sha256': hashlib.sha256(sample).hexdigest(), 'extents': extents,
            'GPU_work_submitted': False}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input', type=Path)
    ap.add_argument('output', type=Path)
    ap.add_argument('--item', type=int, required=True)
    args = ap.parse_args()
    require(args.input.stat().st_size <= 32*1024*1024, 'input too large')
    report = export(args.input.read_bytes(), args.item)
    with args.output.open('x') as handle:
        json.dump(report, handle, indent=2)
        handle.write('\n')
    print(f"Exported item {args.item}: profile {report['configuration']['profile_idc']}, "
          f"chroma {report['configuration']['chroma_format']}; no decode submitted")


if __name__ == '__main__':
    main()
