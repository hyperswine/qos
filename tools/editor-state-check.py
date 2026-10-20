#!/usr/bin/env python3
"""Editor state type boundaries, live transitions, lifecycle and memory parity."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('editor_policy', ROOT / 'tools/editor-policy-check.py')
editor_policy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(editor_policy)


def check(out):
    fprisc = editor_policy.main_profile.fprisc_root()
    env = dict(os.environ, FPR_HOME=str(ROOT), FPR_PATH=str(fprisc),
               FPR_FOREIGN=str(ROOT / 'core/foreign.fpr'))
    prefix = f'unsafe program.\nES = use "{ROOT}/programs/mods/editorstate".\n'
    refusals = {
        'integer-job': 'main = ES.jobName 1.',
        'integer-prompt': 'main = ES.promptName 2.',
        'job-as-prompt': 'main = ES.promptName ES.OpenDocument.',
        'integer-confirmation': 'main = ES.confirmationName 1.',
        'prompt-as-edit': 'main = ES.coalesces ES.Editing.',
        'job-as-action': 'main = ES.CancelPrompt == ES.OpenDocument.',
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
        print(f'Editor state: {name} refused', flush=True)
    editor_policy.check(out, ('editorstate', 'appsession', 'editorpolicy', 'appsessionmemory'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output:
        out = args.output.resolve()
        out.mkdir(parents=True, exist_ok=True)
        check(out)
    else:
        with tempfile.TemporaryDirectory(prefix='qos-editor-state-') as directory:
            check(Path(directory))
