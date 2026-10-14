#!/usr/bin/env python3
"""Exercise an isolated, matching Main bundle on a Pi; preserve its installed session.

The remote directory must contain runner, qosp-es, main.qa and Main.disk.
A separate SD-backed disk is used for both boots. Workload assertions and
shutdown are distinct from sampled residency; global GPU BOs are diagnostic.
"""
import argparse
import base64
import json
from pathlib import Path
import re
import shlex
import struct
import subprocess
import time

from soak import mappings


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--host', required=True)
    ap.add_argument('--identity', required=True)
    ap.add_argument('--known-hosts', required=True)
    ap.add_argument('--host-key-alias')
    ap.add_argument('--remote-dir', required=True)
    ap.add_argument('--viewport', help='force an isolated logical surface, e.g. 1024x600')
    ap.add_argument('--pointer-probe', action='store_true', help='test primary touch tap/cancel through FPR_POINTER_EVDEV')
    ap.add_argument('--harts', type=int, choices=(1, 4), default=4)
    ap.add_argument('--reliability-probe', action='store_true',
                    help='require tests/mainreliability.fpr; F11 checks real reload and a live hung storage peer')
    ap.add_argument('--seconds', type=int, default=1800)
    ap.add_argument('--interval', type=int, default=30)
    ap.add_argument('--max-growth-mib', type=int, default=16)
    ap.add_argument('--arena-mib', type=int, default=256,
                    help='QOS app arena reservation limit in MiB (default 256)')
    ap.add_argument('--memory-probe', action='store_true',
                    help='require tests/mainmemory.fpr as main.qa; sample its F12 allocator probe')
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    if a.seconds < 60 or a.interval <= 0 or a.max_growth_mib < 0 or a.arena_mib < 64:
        ap.error('seconds must be >=60, interval positive, growth nonnegative, arena >=64 MiB')
    if a.viewport:
        viewport = re.fullmatch(r'([0-9]+)x([0-9]+)', a.viewport)
        if not viewport or any(not 64 <= int(n) <= 8192 for n in viewport.groups()):
            ap.error('viewport must be WIDTHxHEIGHT, each 64..8192')
    a.output.mkdir(parents=True, exist_ok=True)
    ssh_args = ['ssh', '-F', '/dev/null', '-i', a.identity, '-o', 'IdentitiesOnly=yes',
                '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                '-o', f'UserKnownHostsFile={a.known_hosts}', '-o', 'ConnectTimeout=5']
    if a.host_key_alias:
        ssh_args += ['-o', 'HostKeyAlias='+a.host_key_alias]
    ssh_args += ['root@'+a.host]

    def ssh(command):
        return subprocess.check_output([*ssh_args, command], text=True, timeout=20)

    stamp = str(time.time_ns())
    base = a.remote_dir.rstrip('/')
    work = base+'/soak-'+stamp
    store = '/var/lib/qosp/check-main-soak-'+stamp
    quote = shlex.quote
    production = ssh('cat /var/run/qosp/state').strip()
    hashes = ssh('sha256sum '+ ' '.join(quote(base+'/'+n) for n in ('qosp-es', 'main.qa', 'Main.disk')))
    ssh('set -e\nmkdir '+quote(work)+' '+quote(store)+'\ncp '+quote(base+'/Main.disk')+' '+quote(store+'/Main.disk'))
    result = {'remote_dir': base, 'work': work, 'store': store, 'bundle_hashes': hashes,
              'production_before': production, 'boots': [], 'memory_probe': a.memory_probe,
              'arena_limit_mib': a.arena_mib, 'harts': a.harts, 'viewport': a.viewport, 'pointer_probe': a.pointer_probe,
              'reliability_probe': a.reliability_probe, 'scope':
              'isolated Main UI workload and two graceful shutdown paths; residency and optional allocator reservations/root counts, not reachability proof'}
    (a.output/'started.json').write_text(json.dumps(result, indent=2)+'\n')

    def logfile(boot):
        return ssh('cat '+quote(work+f'/boot{boot}.log'))

    def wait_log(boot, text, count=1, timeout=30):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            log = logfile(boot)
            if 'PANIC' in log or 'SIGSEGV' in log:
                raise RuntimeError(log[-3000:])
            if log.count(text) >= count:
                return log
            time.sleep(.3)
        raise RuntimeError(f'boot {boot}: waiting for {text!r} #{count}\n{log[-2000:]}')

    def key(boot, code):
        data = b''.join(struct.pack('<qqHHi', 0, 0, 1, code, value) for value in (1, 0))
        encoded = base64.b64encode(data).decode()
        ssh('printf %s '+quote(encoded)+' | base64 -d > '+quote(work+f'/keys{boot}'))
        time.sleep(.2)

    def start(boot, seconds, stop):
        ready, keys = work+f'/ready{boot}', work+f'/keys{boot}'
        pointer = work+f'/pointer{boot}'
        extra = (' FPR_GFX_SIZE='+quote(a.viewport) if a.viewport else '') + (' FPR_POINTER_EVDEV='+quote(pointer) if a.pointer_probe else '')
        command = ('cd '+quote(work)+'\nmkfifo '+quote(keys)+'\n'
                   + ('mkfifo '+quote(pointer)+'\n' if a.pointer_probe else '')
                   + f'FPR_HARTS={a.harts} FPR_HEAP_MB=256 QOSP_ARENA_MB={a.arena_mib} FPR_PORT=0 FPR_EVDEV='+quote(keys)
                   + extra + ' QOSP_READY_FILE='+quote(ready)+' FPR_DISK='+quote(store+'/Main.disk')
                   + ' '+quote(base+'/runner')+f' {seconds+60} {stop} '+quote(work+f'/boot{boot}.log')
                   + ' '+quote(base+'/qosp-es')+' --yes '+quote(base+'/main.qa')
                   + ' > '+quote(work+f'/boot{boot}.json')+' 2> '+quote(work+f'/boot{boot}.err')+' < /dev/null &')
        ssh(command)
        wait_log(boot, 'Main Profile ready (8 shortcuts,')
        return int(ssh('cat '+quote(ready)))

    def collect(boot):
        deadline = time.monotonic()+15
        while time.monotonic() < deadline:
            raw = ssh('cat '+quote(work+f'/boot{boot}.json'))
            if raw.strip():
                break
            time.sleep(.3)
        meta = json.loads(raw)
        log = logfile(boot)
        (a.output/f'boot{boot}.log').write_text(log)
        if meta['exit'] != 0 or meta['signal'] or meta['timeout'] or meta['killed']:
            raise RuntimeError(meta)
        if '[gfx] EGL' not in log or 'V3D' not in log:
            raise RuntimeError('real Pi EGL/V3D backend not exercised')
        ssh('test ! -e '+quote(work+f'/ready{boot}'))
        return meta, log

    pid = None
    try:
        pid = start(1, a.seconds, 0)
        if a.pointer_probe:
            def pointer(events):
                data = b''.join(struct.pack('<qqHHi', 0, 0, *event) for event in events)
                encoded = base64.b64encode(data).decode()
                ssh('printf %s '+quote(encoded)+' | base64 -d > '+quote(work+'/pointer1'))
                time.sleep(.3)
            def touch(value):
                pointer([(3, 0, 65535//8), (3, 1, 65535//3), (1, 0x14a, value), (0, 0, 0)])
            touch(1)
            if 'shell: open clock' in logfile(1): raise RuntimeError('touch launched on press')
            pointer([(0, 3, 0), (0, 0, 0)])
            touch(0)
            if 'shell: open clock' in logfile(1): raise RuntimeError('cancelled touch launched')
            touch(1); touch(0); wait_log(1, 'shell: open clock')
            key(1, 1)
        started = time.monotonic()
        samples = []
        cycles = 0
        with (a.output/'samples.jsonl').open('w') as output:
            while True:
                # Reset the launcher selection each time; exercise both text
                # viewports, their scroll keys, and the onboard Browser.
                for code in (1, 102, 106, 28): key(1, code)
                wait_log(1, 'shell: open files', cycles+1)
                for code in (109, 102, 1, 102, 106, 106, 28): key(1, code)
                wait_log(1, 'shell: open logs', cycles+1)
                for code in (107, 102, 1, 102, 106, 106, 106, 106, 106, 106, 28): key(1, code)
                wait_log(1, 'shell: open browser', cycles+1)
                for code in (108, 28, 1, 102): key(1, code)
                cycles += 1
                if a.reliability_probe:
                    key(1, 87)
                    wait_log(1, 'main-reliability: reload=20/30/20 storage-fault=bounded state=kept', cycles)
                logical = None
                if a.memory_probe:
                    key(1, 88)
                    log = wait_log(1, 'main-memory: ', cycles)
                    rows = re.findall(r'main-memory: arena_kib=(\d+) free_kib=(\d+) roots=(\d+) owner_bumped_bytes=(\d+)', log)
                    if len(rows) != cycles:
                        raise RuntimeError('missing, duplicate or malformed allocator sample')
                    arena, free, roots, bumped = map(int, rows[-1])
                    if free > arena or arena == 0 or arena > a.arena_mib*1024:
                        raise RuntimeError('invalid allocator reservation sample')
                    logical = {'arena_kib': arena, 'free_kib': free,
                               'reserved_kib': arena-free, 'arc_roots': roots,
                               'owner_bumped_bytes': bumped}
                raw = ssh('set -e\np=$(cat '+quote(work+'/ready1')+')\n'
                          'echo SECTION:pid; echo "$p"\n'
                          'echo SECTION:smaps; cat /proc/$p/smaps\n'
                          'echo SECTION:status; cat /proc/$p/status\n'
                          'echo SECTION:bo; cat /sys/kernel/debug/dri/0/bo_stats 2>/dev/null || true\n'
                          'echo SECTION:drm; for f in /proc/$p/fdinfo/*; do '
                          'if grep -q drm-driver "$f"; then echo "$f"; cat "$f"; fi; done\n'
                          'echo SECTION:service; cat /var/run/qosp/state\n'
                          'echo SECTION:temperature; cat /sys/class/thermal/thermal_zone0/temp\n')
                (a.output/f'sample-{cycles:04d}.txt').write_text(raw)
                parts = re.split(r'^SECTION:(\w+)\n', raw, flags=re.M)
                sections = dict(zip(parts[1::2], parts[2::2]))
                if int(sections['pid']) != pid or sections['service'].strip() != production:
                    raise RuntimeError('test PID or installed service changed')
                maps = mappings(sections['smaps'])
                elapsed = time.monotonic()-started
                sample = {'seconds': elapsed, 'cycles': cycles, 'pid': pid,
                          'rss_kib': sum(m.get('Rss', 0) for m in maps),
                          'pss_kib': sum(m.get('Pss', 0) for m in maps),
                          'anonymous_kib': sum(m.get('Anonymous', 0) for m in maps),
                          'bo_global': sections['bo'].strip(),
                          'drm_fdinfo': sections['drm'].strip(),
                          'allocator': logical,
                          'temperature_mc': int(sections['temperature'])}
                samples.append(sample)
                output.write(json.dumps(sample)+'\n'); output.flush()
                print(f'{elapsed:.1f}s cycles={cycles} RSS={sample["rss_kib"]} KiB PSS={sample["pss_kib"]} KiB', flush=True)
                if elapsed >= a.seconds: break
                time.sleep(min(a.interval, a.seconds-elapsed))
        key(1, 16)
        wait_log(1, 'shell: storage drained and flushed')
        meta, _ = collect(1)
        pid = None
        rss = [s['rss_kib'] for s in samples]
        result['boots'].append({'boot': 1, **meta, 'cycles': cycles, 'samples': len(samples),
                                'rss_first_kib': rss[0], 'rss_last_kib': rss[-1],
                                'rss_min_kib': min(rss), 'rss_max_kib': max(rss)})
        if a.memory_probe:
            result['boots'][-1]['allocator_first'] = samples[0]['allocator']
            result['boots'][-1]['allocator_last'] = samples[-1]['allocator']
        if max(rss)-rss[0] > a.max_growth_mib*1024:
            raise RuntimeError(f'RSS growth exceeded {a.max_growth_mib} MiB: {rss[0]} -> {max(rss)} KiB')
        pid = start(2, 45, 30)
        wait_log(2, 'qosp: shutdown complete', timeout=60)
        meta, _ = collect(2)
        pid = None
        if not meta['stop_requested']: raise RuntimeError('signal shutdown was not requested')
        result['boots'].append({'boot': 2, **meta})
        result['production_after'] = ssh('cat /var/run/qosp/state').strip()
        if result['production_after'] != production: raise RuntimeError('installed service changed')
        result['passed'] = True
        # Remove only this run's successfully drained, isolated disk.
        ssh('rm '+quote(store+'/Main.disk')+'\nrmdir '+quote(store))
        (a.output/'complete.json').write_text(json.dumps(result, indent=2)+'\n')
        print('Main workload, residency threshold, normal quit and signal shutdown PASS', flush=True)
    except Exception as error:
        result['passed'] = False
        result['error'] = str(error)
        (a.output/'failed.json').write_text(json.dumps(result, indent=2)+'\n')
        if pid is not None:
            # Kill only our isolated runner's child, never a production PID.
            ssh(f'kill -TERM {pid} 2>/dev/null || true')
        raise


if __name__ == '__main__':
    main()
