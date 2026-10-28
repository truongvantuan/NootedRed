"""Summarize bounded VCN context trace messages from one boot, without workloads."""
import re


def summarize(text):
    pairs = {}
    conflicts = []
    for line in text.splitlines():
        if 'VCNTrace' not in line:
            continue
        match = re.search(r'\b(begin|end) op=(newContext|removeContext) pid=(\d+)(?: result=(0x[0-9a-fA-F]+))? event=(\d+)', line)
        if not match:
            continue
        phase, operation, pid, result, event = match.groups()
        key = (int(pid), int(event))
        pair = pairs.setdefault(key, {'pid': key[0], 'event': key[1], 'operation': operation})
        if pair['operation'] != operation:
            conflicts.append({'pid': key[0], 'event': key[1], 'reason': 'operation changed'})
        if phase in pair and pair[phase] != line:
            conflicts.append({'pid': key[0], 'event': key[1], 'reason': 'conflicting repeated phase'})
        pair[phase] = line
        if result is not None:
            pair['native_status'] = int(result, 16)
    values = list(pairs.values())
    return {
        'events': values,
        'completed': [p for p in values if 'begin' in p and 'end' in p],
        'unmatched_begins': [p for p in values if 'begin' in p and 'end' not in p],
        'end_without_begin': [p for p in values if 'end' in p and 'begin' not in p],
        'native_errors': [p for p in values if p.get('native_status', 0) != 0],
        'conflicts': conflicts,
        'note': 'Trace pairs alone do not prove codec identity or a repair. An unmatched phase may reflect capture boundaries or a call in progress.'}
