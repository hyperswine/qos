#!/usr/bin/env python3
"""Compile QOS entries and inventory receive SCC decisions, without running them.

Counts are receive-reaching recursive groups in the compiled dependency
closure, including exports that may not execute; not actor counts or memory proofs. Explicit region owners stay a separate category.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def decisions(log):
    groups = {}
    for line in log.splitlines():
        match = re.match(r'receive-turns: (.*?): (.*)', line)
        if not match:
            continue
        names, reason = match.groups()
        # Whole-program and unit-local compilations allocate different private
        # join numbers. Source names retain their content-addressed unit hash.
        members = sorted(n for n in names.split()
                         if not re.fullmatch(r'case_join_\d+|.*_fb_\d+', n))
        key = tuple(members)
        status = ('automatic' if reason.startswith('automatic value-state') else
                  'explicit_region' if reason.startswith('explicit region') else
                  'skipped')
        item = groups.setdefault(key, {'members': members, 'status': status, 'reasons': []})
        if item['status'] != status:
            raise RuntimeError(f'inconsistent whole/unit decisions for {members}: {item["status"]} / {status}')
        if reason not in item['reasons']:
            item['reasons'].append(reason)
    return sorted(groups.values(), key=lambda g: g['members'])


def expectation_errors(result, expectations):
    errors = []
    for entry in result['entries']:
        required = expectations.get(entry['entry'])
        if required is None:
            errors.append(f'{entry["entry"]}: no coverage expectation recorded')
            continue
        for name in required:
            matches = [g for g in entry['groups']
                       if any(n.split('@')[0] == name for n in g['members'])]
            if not matches or any(g['status'] == 'skipped' for g in matches):
                errors.append(f'{entry["entry"]}: {name} is missing or skipped')
    return errors


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--compiler', type=Path, default=ROOT.parent/'fprisc/fpr')
    ap.add_argument('--entry', action='append', help='repeat to audit multiple entries; default Main and onboard apps')
    ap.add_argument('--target', default='qa64mac' if platform.system() == 'Darwin' else
                    'qa64' if platform.machine() == 'aarch64' else 'qx64')
    ap.add_argument('--out', type=Path, required=True, help='JSON output; compiler logs saved alongside it')
    ap.add_argument('--check', action='store_true', help='require recorded groups to retain automatic or explicit boundaries')
    ap.add_argument('--expectations', type=Path, default=ROOT/'tools/receive-coverage-expectations.json')
    args = ap.parse_args()
    entries = args.entry or ['programs/main.fpr', 'apps/clock.fpr', 'apps/logs.fpr',
                             'apps/browser.fpr', 'apps/disk.fpr']
    compiler = args.compiler.resolve()
    env = {**os.environ, 'FPR_HOME': str(ROOT), 'FPR_PATH': str(compiler.parent),
           'FPR_FOREIGN': str(ROOT/'core/foreign.fpr'), 'FPR_RECEIVE_NOTES': '1'}
    env.pop('FPR_NO_RECEIVE_TURNS', None)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    result = {'compiler': str(compiler), 'target': args.target, 'entries': []}
    with tempfile.TemporaryDirectory(prefix='qos-receive-coverage-') as tmp:
        for i, entry in enumerate(entries):
            command = [str(compiler), 'compile', '--target='+args.target, entry, str(Path(tmp)/f'entry{i}.s')]
            proc = subprocess.run(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, timeout=300)
            log_path = args.out.with_name(args.out.stem+f'-{i}-{Path(entry).stem}.log')
            log_path.write_text(proc.stdout)
            if proc.returncode:
                raise RuntimeError(f'{entry}: compilation failed; see {log_path}')
            groups = decisions(proc.stdout)
            counts = dict(Counter(g['status'] for g in groups))
            result['entries'].append({'entry': entry, 'counts': counts, 'groups': groups})
            print(f'{entry}: {counts}', flush=True)
    result['expectation_errors'] = (expectation_errors(result, json.loads(args.expectations.read_text()))
                                    if args.check else [])
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(f'Inventory: {args.out}')
    if result['expectation_errors']:
        raise SystemExit('\n'.join(result['expectation_errors']))


if __name__ == '__main__':
    main()
