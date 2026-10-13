#!/usr/bin/env python3
"""Run the matching candidate's storage fixtures on isolated Pi SD disks."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import time
ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--host', required=True)
ap.add_argument('--identity', required=True)
ap.add_argument('--known-hosts', required=True)
ap.add_argument('--host-key-alias')
ap.add_argument('--remote-dir', required=True)
ap.add_argument('--output', required=True, type=Path)
a = ap.parse_args()
a.output.mkdir(parents=True, exist_ok=False)
args = ['ssh', '-F', '/dev/null', '-i', a.identity, '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
        '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile='+a.known_hosts, '-o', 'ConnectTimeout=5']
if a.host_key_alias: args += ['-o', 'HostKeyAlias='+a.host_key_alias]
args += ['root@'+a.host]
def ssh(command, timeout=70):
    return subprocess.check_output([*args, command], text=True, timeout=timeout)
quote = shlex.quote
base = a.remote_dir.rstrip('/')
stamp = str(time.time_ns())
work = base+'/storage-'+stamp
store = '/var/lib/qosp/check-storage-'+stamp
production = ssh('cat /var/run/qosp/state').strip()
model = ssh('cat /proc/device-tree/model').rstrip('\0\n')
assert 'Raspberry Pi 4 Model B' in model, model
ssh('set -e\nmkdir '+quote(work)+' '+quote(store))
results = []
for name in ('inbox', 'inboxshared', 'inboxownership'):
    for harts in (1, 4):
        case = name+'-h'+str(harts)
        log = work+'/'+case+'.log'
        command = [base+'/runner', '60', '0', log, 'env',
                   'FPR_HARTS='+str(harts), 'FPR_HEAP_MB=64', base+'/'+name+'-base']
        meta = json.loads(ssh('cd '+quote(work)+'\n'+shlex.join(command)))
        text = ssh('cat '+quote(log))
        (a.output/(case+'.log')).write_text(text)
        passed = meta['exit'] == 0 and not meta['signal'] and not meta['timeout'] and not meta['killed'] and 'HOLDS' in text and 'PANIC' not in text
        results.append({'name': case, **meta, 'passed': passed})
        print(case+': '+('PASS' if passed else 'FAIL'), flush=True)
        if not passed: raise RuntimeError(text[-4000:])
for name in ('storagedeadlines', 'storagebudgets', 'blockmemory', 'filesshutdown', 'filessvc'):
    for harts in (1, 4):
        case = name+'-h'+str(harts)
        disk = store+'/'+case+'.disk'
        log = work+'/'+case+'.log'
        values = ['FPR_HARTS='+str(harts), 'FPR_PORT=0', 'FPR_DISK='+disk, 'QOSP_ARENA_MB=256']
        if name == 'storagebudgets': values += ['QOS_BLK_TEST_DELAY_US=100000']
        command = [base+'/runner', '60', '0', log, 'env', *values, base+'/qosp-es', '--yes', base+'/'+name+'.qa']
        raw = ssh('cd '+quote(work)+'\n'+shlex.join(command))
        meta = json.loads(raw)
        text = ssh('cat '+quote(log))
        (a.output/(case+'.log')).write_text(text)
        passed = meta['exit'] == 0 and not meta['signal'] and not meta['timeout'] and not meta['killed'] and 'HOLDS' in text and 'FAILED' not in text and 'PANIC' not in text
        results.append({'name': case, **meta, 'passed': passed})
        (a.output/'results.json').write_text(json.dumps({'model': model, 'production_before': production, 'cases': results}, indent=2)+'\n')
        print(case+': '+('PASS' if passed else 'FAIL'), flush=True)
        if not passed: raise RuntimeError(text[-4000:])
        ssh('rm '+quote(disk))
assert ssh('cat /var/run/qosp/state').strip() == production, 'installed service changed'
ssh('rmdir '+quote(store))
(a.output/'complete.json').write_text(json.dumps({'passed': True, 'model': model, 'production_before': production, 'production_after': production, 'cases': results}, indent=2)+'\n')
