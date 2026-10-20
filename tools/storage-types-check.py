#!/usr/bin/env python3
"""Storage type boundaries, v1/v2 compatibility and live schema discovery."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('editor_policy', ROOT / 'tools/editor-policy-check.py')
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


def check(out):
    fprisc = runner.main_profile.fprisc_root()
    env = dict(os.environ, FPR_HOME=str(ROOT), FPR_PATH=str(fprisc),
               FPR_FOREIGN=str(ROOT / 'core/foreign.fpr'))
    prefix = (f'unsafe program.\nP = use "{ROOT}/std/storageprotocol".\n'
              f'C = use "{ROOT}/std/storageclient".\n')
    refusals = {
        'integer-operation': 'main = P.encode P.DeadlineV2 P.FilesOwner 2.',
        'integer-version': 'main = P.encode 2 P.FilesOwner P.Compact.',
        'integer-target-kind': 'main = P.encode P.DeadlineV2 1 P.Compact.',
        'bare-actor': 'main = C.request (myself 0) 42 P.Compact.',
        'string-error': 'main = P.missing "no such file".',
        'error-as-operation': 'main = P.name (P.fromLegacy "no disk").',
    }
    for name, body in refusals.items():
        source = out / (name + '.fpr')
        source.write_text(prefix + body + '\n')
        result = subprocess.run([str(fprisc / 'fpr'), '--profile=qos-portable',
                                 f'--prelude={fprisc}/core/prelude.fpr', '--check-only',
                                 str(source), str(out / (name + '.s'))],
                                cwd=ROOT, env=env, capture_output=True, text=True, timeout=240)
        log = result.stdout + result.stderr
        (out / (name + '.log')).write_text(log)
        assert result.returncode == 1 and 'cannot unify' in log, log
        print(f'Storage types: {name} refused', flush=True)
    runner.check(out, ('storageprotocol', 'filessvc', 'appsessionmemory'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output:
        out = args.output.resolve()
        out.mkdir(parents=True, exist_ok=True)
        check(out)
    else:
        with tempfile.TemporaryDirectory(prefix='qos-storage-types-') as directory:
            check(Path(directory))
