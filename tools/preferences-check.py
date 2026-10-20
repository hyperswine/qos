#!/usr/bin/env python3
"""Live Editor/Terminal preferences, retention and recovery job boundaries."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('runner', ROOT / 'tools/editor-policy-check.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def check(out):
    fprisc = runner.main_profile.fprisc_root()
    env = dict(os.environ, FPR_HOME=str(ROOT), FPR_PATH=str(fprisc),
               FPR_FOREIGN=str(ROOT / 'core/foreign.fpr'))
    imports = (f'unsafe program.\nE = use "{ROOT}/programs/mods/editorpreferences".\n'
               f'T = use "{ROOT}/programs/mods/terminalpreferences".\n'
               f'H = use "{ROOT}/programs/mods/preferencehistory".\n')
    refusals = {
        'integer-editor': 'main = E.undoDepth 200.',
        'integer-terminal': 'main = T.inputBytes 240.',
        'crossed-preferences': 'main = E.undoDepth T.defaults.',
        'string-retention': 'main = E.Preferences 2 3 "/home/.editor/session" "keep-newest".',
        'boolean-retention': 'main = T.Preferences 240 400 50 True.',
    }
    for name, body in refusals.items():
        source = out / (name + '.fpr')
        source.write_text(imports + body + '\n')
        result = subprocess.run([str(fprisc / 'fpr'), '--profile=qos-portable',
                                 f'--prelude={fprisc}/core/prelude.fpr', '--check-only',
                                 source, out / (name + '.s')], cwd=ROOT, env=env,
                                capture_output=True, text=True, timeout=240)
        log = result.stdout + result.stderr
        (out / (name + '.log')).write_text(log)
        assert result.returncode == 1 and 'cannot unify' in log, log
        print(f'Preferences: {name} refused', flush=True)
    runner.check(out, ('preferences', 'preferencesrecovery', 'editorstate', 'appsession', 'appsessionmemory'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output:
        directory = args.output.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        check(directory)
    else:
        with tempfile.TemporaryDirectory(prefix='qos-preferences-') as directory:
            check(Path(directory))
