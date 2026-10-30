#!/usr/bin/env python3
"""Two-phase package upgrade acceptance, reusing the installed SDK counter disk.

Run prepare after portable-sdk-check.py --gui. Upgrade the actual package, then
run verify against its new prefix. Both phases use installed tools; verify
blocks checkout/build-tool access with the earlier acceptance policy.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(out, prefix, args, log, cwd=None, extra=None):
    restricted = out / 'path'
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('FPR', 'QOS', 'PYTHON')) and k not in ('HOME', 'PATH', 'XDG_CACHE_HOME')}
    env.update(PATH=f'{prefix / "bin"}:{restricted}', HOME=str(out / 'home'),
               XDG_CACHE_HOME=str(out / 'cache'), PYTHONDONTWRITEBYTECODE='1')
    env.update(extra or {})
    result = subprocess.run(['/usr/bin/sandbox-exec', '-f', str(out / 'source-free.sb'), *map(str, args)],
                            cwd=cwd or out, env=env, capture_output=True, text=True, timeout=240)
    (out / log).write_text(result.stdout + result.stderr)
    if result.returncode:
        raise ValueError(f'{log}: exit {result.returncode}: {result.stdout[-1500:]}{result.stderr[-1500:]}')
    return result.stdout + result.stderr


def records(out, prefix, expected=None):
    sdk = prefix / 'libexec/qos-portable'
    disk = out / 'counter.disk'
    script = f'import sys,json,hashlib;sys.path.insert(0,{str(sdk / "tools")!r});import qos_disk as d\n'
    script += f'with d.locked({str(disk)!r}) as fd:\n'
    if expected is not None:
        script += " values=d.scan(fd,d.metadata(fd));assert values[b'app-data/counter-example/636f756e74'].read(fd)==b'2'\n"
        script += " d.append(fd,d.metadata(fd),[(b'test/sdk/expected-count',b'2')])\n"
    script += ' print(json.dumps({k.decode():hashlib.sha256(v.read(fd)).hexdigest() for k,v in d.scan(fd,d.metadata(fd)).items()},sort_keys=True))\n'
    return json.loads(execute(out, prefix, [out / 'path/python3', '-c', script], 'upgrade-records.log'))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('phase', choices=['prepare', 'verify'])
    ap.add_argument('--sdk', type=Path, required=True)
    ap.add_argument('--acceptance', type=Path, required=True)
    args = ap.parse_args()
    out, prefix = args.acceptance.resolve(), args.sdk.resolve()
    sdk = prefix / 'libexec/qos-portable'
    meta = json.loads((sdk / 'sdk.json').read_text())
    prior = json.loads((out / 'evidence.json').read_text())
    if prior['result'] != 'passed' or not prior['graphicalMain']:
        ap.error('requires a passing graphical installed SDK acceptance')
    disk = out / 'counter.disk'
    before_path = out / 'upgrade-before.json'
    if args.phase == 'prepare':
        if before_path.exists():
            ap.error('upgrade already prepared')
        if meta.get('release') != prior['sdk'].get('release') or not meta.get('release'):
            ap.error('prepare must use the tested installed release')
        values = records(out, prefix, expected=2)
        before_path.write_text(json.dumps(dict(release=meta['release'], abi=meta['abi'],
            desktopApi=meta['desktopApi'], desktopSession=meta['desktopSession'],
            diskSha256=digest(disk), records=values), indent=2) + '\n')
        print('Upgrade prepared: counter=2; disk and all records fingerprinted')
        return
    before = json.loads(before_path.read_text())
    if before['release'] == meta.get('release'):
        ap.error('install a different package release before verify')
    if any(before[k] != meta[k] for k in ('abi', 'desktopApi', 'desktopSession')):
        ap.error('this check qualifies compatible package upgrades only; profile migration is separate')
    if digest(disk) != before['diskSha256'] or records(out, prefix) != before['records']:
        ap.error('package upgrade changed the user disk before QOS launched')
    probe = 'import shutil;assert all(shutil.which(x) is None for x in ("ghc","cabal","make"));print("build tools absent")'
    execute(out, prefix, [out / 'path/python3', '-c', probe], 'upgrade-access-probe.log')
    # A new archive from the upgraded compiler/SDK replaces the app by stable ID.
    project = out / 'renamed project'
    manifest = project / 'qos.toml'
    manifest.write_text(manifest.read_text().replace('"1.2.4"', '"1.2.5"'))
    execute(out, prefix, [prefix / 'bin/qos', 'build'], 'upgrade-build.log', cwd=project)
    execute(out, prefix, [prefix / 'bin/qos', 'install', project / 'build/counter-example.qa', disk], 'upgrade-install.log')
    run = execute(out, prefix, [sdk / 'runtime/qosp', '--yes', out / 'driver.qa'], 'upgrade-session.log',
                  extra={'FPR_DISK': str(disk), 'FPR_HARTS': '4'})
    if 'sdkdesktop: HOLDS persisted=1 loaded=2' not in run:
        ap.error(f'upgraded package did not restore the saved count: {run}')
    after = records(out, prefix)
    changed = {'apps/index', 'apps/counter-example.qa', 'test/sdk/expected-count',
               'app-data/counter-example/636f756e74'}
    if any(after.get(k) != v for k, v in before['records'].items() if k not in changed):
        ap.error('upgraded runtime or app replacement changed unrelated records')
    evidence = dict(result='passed', fromRelease=before['release'], toRelease=meta['release'],
                    os=meta['os'], architecture=meta['architecture'], packageLeftDiskByteIdentical=True,
                    loadedCount=2, upgradedCompilerBuild=True, appReplacement=True,
                    unrelatedRecordsPreserved=True, sourceAccess='denied by sandbox-exec',
                    absentTools=['ghc', 'cabal', 'make'], sdk=meta)
    (out / 'upgrade-evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print('Installed package upgrade: HOLDS (saved count=2 restored with upgraded SDK/runtime)')


if __name__ == '__main__':
    main()
