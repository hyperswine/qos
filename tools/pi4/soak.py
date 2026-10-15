#!/usr/bin/env python3
"""Observe one installed QOS process without restarting it or changing its disk.

Samples Linux smaps and V3D BO diagnostics over public-key SSH. A changed PID,
lost readiness, or failed sample fails the run. This measures residency and
kernel buffer ownership, not the runtime's logical live allocation count.
"""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import time


def mappings(raw):
    rows = []
    for line in raw.splitlines():
        if re.match(r'^[0-9a-f]+-[0-9a-f]+ ', line):
            parts = line.split(maxsplit=5)
            rows.append({'range': parts[0], 'permissions': parts[1],
                         'path': parts[5] if len(parts) == 6 else ''})
        elif rows:
            match = re.match(r'^(\w+):\s+(\d+) kB$', line)
            if match:
                rows[-1][match[1]] = int(match[2])
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--host', required=True)
    ap.add_argument('--identity', required=True)
    ap.add_argument('--known-hosts', required=True)
    ap.add_argument('--host-key-alias')
    ap.add_argument('--seconds', type=int, default=1800)
    ap.add_argument('--interval', type=int, default=30)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--ready-file', default='/var/run/qosp/ready')
    ap.add_argument('--app', default='/usr/share/qosp/app.qa')
    a = ap.parse_args()
    if a.seconds <= 0 or a.interval <= 0:
        ap.error('seconds and interval must be positive')
    a.output.mkdir(parents=True, exist_ok=True)
    ssh = ['ssh', '-F', '/dev/null', '-i', a.identity, '-o', 'IdentitiesOnly=yes',
           '-o', 'BatchMode=yes', '-o', f'UserKnownHostsFile={a.known_hosts}',
           '-o', 'ConnectTimeout=5']
    if a.host_key_alias:
        ssh += ['-o', 'HostKeyAlias='+a.host_key_alias]
    ssh += [f'root@{a.host}']
    command = 'set -e\np=$(cat ' + shlex.quote(a.ready_file) + ')\n' + '''
case "$p" in ''|*[!0-9]*) exit 2;; esac
echo SECTION:pid; echo "$p"
echo SECTION:uptime; cat /proc/uptime
echo SECTION:status; cat /proc/$p/status
echo SECTION:stat; cat /proc/$p/stat
echo SECTION:smaps; cat /proc/$p/smaps
echo SECTION:meminfo; cat /proc/meminfo
echo SECTION:bo; cat /sys/kernel/debug/dri/0/bo_stats 2>/dev/null || true
echo SECTION:gpu; cat /sys/kernel/debug/dri/0/gpu_pid_usage 2>/dev/null || true
echo SECTION:temperature; cat /sys/class/thermal/thermal_zone0/temp
echo SECTION:frequency; cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq
echo SECTION:service; cat /var/run/qosp/state
echo SECTION:binary; sha256sum /proc/$p/exe ''' + shlex.quote(a.app) + '\n'
    started = time.monotonic()
    pid = None
    count = 0
    with (a.output / 'samples.jsonl').open('w') as samples:
        while True:
            result = subprocess.run([*ssh, command], capture_output=True, text=True, timeout=20)
            result.check_returncode()
            (a.output / f'{count:04d}.txt').write_text(result.stdout)
            parts = re.split(r'^SECTION:(\w+)\n', result.stdout, flags=re.M)
            sections = dict(zip(parts[1::2], parts[2::2]))
            current = int(sections['pid'])
            pid = current if pid is None else pid
            if current != pid:
                raise SystemExit(f'FAIL: application PID changed from {pid} to {current}')
            maps = mappings(sections['smaps'])
            memory = {k: int(v) for k, v in re.findall(r'^(\w+):\s+(\d+) kB', sections['meminfo'], re.M)}
            bo = {k.strip(): int(v) for k, v in re.findall(r'^([^:]+):\s+(\d+)', sections['bo'], re.M)}
            rss = sum(m.get('Rss', 0) for m in maps)
            anon = sum(m.get('Anonymous', 0) for m in maps)
            elapsed = time.monotonic() - started
            sample = {'seconds': elapsed, 'pid': pid, 'rss_kib': rss,
                      'anonymous_kib': anon, 'maps': maps, 'meminfo': memory,
                      'bo': bo, 'temperature_mc': int(sections['temperature']),
                      'frequency_khz': int(sections['frequency']),
                      'stat': sections['stat'].strip(), 'service': sections['service'].strip()}
            samples.write(json.dumps(sample) + '\n')
            samples.flush()
            print(f'{elapsed:.1f}s pid={pid} RSS={rss}KiB BO={bo}', flush=True)
            count += 1
            if elapsed >= a.seconds:
                break
            time.sleep(min(a.interval, a.seconds - elapsed))
    (a.output / 'complete.json').write_text(json.dumps({
        'passed': True, 'pid': pid, 'seconds': elapsed, 'samples': count,
        'scope': 'same ready process, successful memory samples; no application workload assertions'
    }, indent=2) + '\n')


if __name__ == '__main__':
    main()
