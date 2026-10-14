#!/usr/bin/env python3
"""Correlate the diagnostic FP-RISC model with native monotonic timestamps.

A frame must carry the updated model's sequence before it can satisfy an
input measurement. An arbitrary render following an input poll cannot.
Offscreen submission is not GPU completion or physical display latency.
"""
import argparse
from collections import defaultdict, deque
import json
import math
from pathlib import Path
import re


def distribution(values):
    values = sorted(values)
    if not values:
        return {'count': 0}
    def percentile(p):
        return values[max(0, math.ceil(p * len(values)) - 1)] / 1000
    return {'count': len(values), 'p50_ms': percentile(.50),
            'p95_ms': percentile(.95), 'p99_ms': percentile(.99),
            'max_ms': values[-1] / 1000}


def report(text):
    pending = defaultdict(deque)
    updates = {}
    frames = []
    samples = []
    view = None
    seen_view = False
    startup_frames = 0
    claimed = set()
    for line in text.splitlines():
        # Portable mirrors HAL logs to stderr with this prefix. Count the
        # original record once, even when stdout/stderr share a capture.
        if line.startswith('[host] '):
            continue
        data = {key: int(value) for key, value in re.findall(r'(\w+)=(-?\d+)', line)}
        if '[gfx-profile] input ' in line:
            if data['kind'] == 4 and data['b'] == 1:
                pending[data['a']].append(data['us'])
        elif 'gui-profile: update ' in line:
            seq, key = data['seq'], data['key']
            if seq in updates:
                raise ValueError('duplicate input sequence')
            if data['end_us'] < data['begin_us']:
                raise ValueError('reversed update timestamps')
            delivered = pending[key].popleft() if pending[key] else None
            if delivered is not None and delivered > data['begin_us']:
                raise ValueError('input received before native delivery')
            updates[seq] = dict(data, delivered_us=delivered)
        elif 'gui-profile: view ' in line:
            seen_view = True
            if view is not None:
                raise ValueError('view did not reach the graphics backend')
            if data['end_us'] < data['begin_us']:
                raise ValueError('reversed view timestamps')
            view = data
        elif '[gfx-profile] frame ' in line:
            if not view:
                if not seen_view:
                    startup_frames += 1
                    continue
                raise ValueError('native frame without a diagnostic model')
            if not (view['end_us'] <= data['start_us'] <= data['drawn_us'] <= data['submitted_us'] <= data['end_us']):
                raise ValueError('reversed frame timestamps')
            frame = dict(data, view=view)
            frames.append(frame)
            seq = view['seq']
            if seq and seq not in claimed:
                update = updates.get(seq)
                if update is None or update['begin_us'] != view['input_us'] or update['key'] != view['key']:
                    raise ValueError('frame/input identity mismatch')
                if update['end_us'] > view['begin_us']:
                    raise ValueError('view precedes update completion')
                sample = {'seq': seq, 'key': view['key'],
                          'update_us': update['end_us'] - update['begin_us'],
                          'finish': data['finish'], 'retained': data['retained']}
                if not data['retained']:
                    sample['update_to_submission_us'] = data['submitted_us'] - update['begin_us']
                if update['delivered_us'] is not None:
                    sample['poll_to_update_us'] = update['begin_us'] - update['delivered_us']
                    if not data['retained']:
                        sample['poll_to_submission_us'] = data['submitted_us'] - update['delivered_us']
                    if data['finish'] and not data['retained']:
                        sample['poll_to_completion_us'] = data['end_us'] - update['delivered_us']
                samples.append(sample)
                claimed.add(seq)
            view = None
    if view is not None:
        raise ValueError('incomplete final frame')
    if not frames or not samples:
        raise ValueError('missing profile frames or correlated inputs')
    # All updates are measured; a drained batch can coalesce older inputs into
    # the newest model. Report those separately instead of fabricating latency.
    metrics = {name: distribution([s[name] for s in samples if name in s]) for name in
               ('update_us', 'poll_to_update_us', 'update_to_submission_us',
                'poll_to_submission_us', 'poll_to_completion_us')}
    metrics.update(view_us=distribution([f['view']['end_us'] - f['view']['begin_us'] for f in frames]),
                   native_draw_us=distribution([f['drawn_us'] - f['start_us'] for f in frames]),
                   present_call_us=distribution([f['submitted_us'] - f['drawn_us'] for f in frames]),
                   gpu_wait_us=distribution([f['end_us'] - f['submitted_us'] for f in frames if f['finish']]),
                   frame_interval_us=distribution([b['start_us'] - a['start_us'] for a, b in zip(frames, frames[1:])]))
    return {'frames': len(frames), 'unmeasured_startup_frames': startup_frames, 'retained_frames': sum(f['retained'] for f in frames),
            'inputs_updated': len(updates), 'inputs_with_frame': len(samples),
            'updates_without_frame': sorted(set(updates) - claimed), 'metrics': metrics, 'samples': samples,
            'scope': 'native poll to first submitted frame carrying that updated model; diagnostic logging enabled; not device-to-photon latency'}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('log', type=Path)
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    result = report(args.log.read_text())
    encoded = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.write_text(encoded)
    else:
        print(encoded, end='')
