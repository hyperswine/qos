#!/usr/bin/env python3
"""Bounded Qlog allocation, binary reads, replay/compaction and two-boot persistence.

Default: local Portable host. --host runs an existing Pi host with the supplied
AArch64 archive and runner, using a separate SD-backed disk. Never replaces
the appliance, reboots it, or reads provisioning inputs.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def seed(path):
    spec = importlib.util.spec_from_file_location('durable', ROOT / 'tools/portable-durable-check.py')
    fmt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fmt)
    pages = 8192
    data_end = pages - pages // 8
    image = bytearray(pages * fmt.PG)
    cursor = 1

    def record(tag, key, payload):
        nonlocal cursor
        count = (len(payload) + fmt.PG - 1) // fmt.PG
        fmt.put(image, cursor, f'{tag} {count} {len(payload)} {key} h{fmt.hh(payload)}\n'.encode())
        for i in range(count):
            fmt.put(image, cursor + i + 1, payload[i * fmt.PG:(i + 1) * fmt.PG])
        cursor += count + 1

    record('QREC', 'seed/blob', bytes(range(256)) * 4096 + bytes(range(17)))
    packed = b'5 seed/bulk\nalpha4 seed/bulk\nbeta5 seed/other\ngamma'
    record('QBLK', '3', packed)
    for p, generation in ((0, 10), (pages - 1, 11)):
        fmt.put(image, p, fmt.seal(cursor, generation, d=data_end))
    path.write_bytes(image)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, default=ROOT / '.qos/qlog-memory')
    ap.add_argument('--archive', type=Path)
    ap.add_argument('--host')
    ap.add_argument('--identity')
    ap.add_argument('--known-hosts')
    ap.add_argument('--runner', type=Path)
    a = ap.parse_args()
    if a.host and not all((a.archive, a.identity, a.known_hosts, a.runner)):
        ap.error('--host requires --archive, --identity, --known-hosts and --runner')
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=True)

    def run(argv, **kw):
        p = subprocess.run(list(map(str, argv)), capture_output=True, text=True,
                           timeout=600, **kw)
        if p.returncode:
            raise RuntimeError(f'{argv}: {p.returncode}\n{p.stdout}{p.stderr}')
        return p.stdout + p.stderr

    archive = a.archive.resolve() if a.archive else out / 'qlogmemory.qa'
    host = out / 'qosp'
    if not a.host:
        if not a.archive:
            (out / 'build.log').write_text(run(['make', '-s', 'qos-app',
                'PROG=tests/qlogmemory.fpr', f'QA_OUT={archive}', f'BUILD={out}/build'], cwd=ROOT))
        (out / 'host-build.log').write_text(run(['make', '-s', 'portable', f'QOSP_OUT={host}'], cwd=ROOT / 'qos'))
    image = out / 'seed.disk'
    seed(image)
    ssh = []
    remote = persistent = ''
    if a.host:
        opts = ['-F', '/dev/null', '-i', a.identity, '-o', 'IdentitiesOnly=yes',
                '-o', 'BatchMode=yes', '-o', f'UserKnownHostsFile={a.known_hosts}',
                '-o', 'ConnectTimeout=5']
        target = f'root@{a.host}'
        ssh = ['ssh', *opts, target]
        tag = str(time.time_ns())
        remote, persistent = f'/tmp/qlog-memory-{tag}', f'/var/lib/qosp/qlog-memory-{tag}'
        (out / 'remote.json').write_text(json.dumps({'work': remote, 'disk': persistent}) + '\n')
        run([*ssh, f'mkdir -p {remote} {persistent}'])
        for source, name in ((archive, 'app.qa'), (a.runner.resolve(), 'runner'), (image, 'seed.disk')):
            run(['scp', '-q', *opts, source, f'{target}:{remote}/{name}'])
        run([*ssh, f'chmod 700 {remote}/runner'])
    results = []
    for harts in (1, 4):
        disk = out / f'h{harts}.disk'
        if a.host:
            run([*ssh, f'cp {remote}/seed.disk {persistent}/h{harts}.disk'])
        else:
            disk.write_bytes(image.read_bytes())
        for boot in (1, 2):
            name = f'h{harts}-boot{boot}'
            if a.host:
                log = f'{remote}/{name}.log'
                command = [f'{remote}/runner', '580', '0', log, 'env',
                           f'FPR_HARTS={harts}', 'FPR_HEAP_MB=64', 'FPR_PORT=0',
                           f'FPR_DISK={persistent}/h{harts}.disk', '/usr/bin/qosp', '--yes', f'{remote}/app.qa']
                raw = run([*ssh, shlex.join(command)])
                (out / f'{name}.json').write_text(raw)
                stats = json.loads(raw)
                assert stats['exit'] == 0 and stats['signal'] == 0 and not stats['timeout'] and not stats['killed'], stats
                text = run([*ssh, f'cat {log}'])
            else:
                text = run([host, '--yes', archive], cwd=out,
                    env={**os.environ, 'FPR_HARTS': str(harts), 'FPR_HEAP_MB': '64',
                         'FPR_PORT': '0', 'FPR_DISK': str(disk)})
            (out / f'{name}.log').write_text(text)
            assert 'qlogmemory: HOLDS' in text, text
            results.append(name)
            print(f'Qlog memory: {name}, 64 MiB heap, binary reads/replay/mutations/compaction HOLDS', flush=True)
    (out / 'complete.json').write_text(json.dumps({
        'passed': True, 'cases': results,
        'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
        'seed_sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
        'qlog_sampled_pool_limit_bytes': 4194304,
        'global_heap_limit_mib': 64,
        'global_growth_is_bounded': False,
    }, indent=2) + '\n')
    if a.host:
        # Keep logs/archives, remove only this test's SD-backed disk copies.
        run([*ssh, f'rm {persistent}/h1.disk {persistent}/h4.disk; rmdir {persistent}'])


if __name__ == '__main__':
    main()
