"""Run the actual sweep legs against controlled successes and failures.

The outer || handler disables Bash errexit inside a leg. Test its verdict,
including the sweep's final exit status, rather than relying on set -e.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def leg(prefix):
    lines = (ROOT / "check-all.sh").read_text().splitlines()
    start = next(i for i, line in enumerate(lines)
                 if line.startswith('echo "== ' + prefix))
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith('echo "== ')), len(lines) - 1)
    return "\n".join(lines[start:end])


class SweepVerdicts(unittest.TestCase):
    def run_leg(self, prefix, mode, success):
        with tempfile.TemporaryDirectory(prefix="qos-sweep-test-") as temp:
            root = Path(temp)
            compiler = root / "compiler"
            (compiler / "sol/examples").mkdir(parents=True)
            (compiler / "tests").mkdir()
            (root / "tests").mkdir()
            (compiler / "tests/txnabort.sol").write_text(
                '> h = open @/tmp/sol-txnabort.txt; close h.\n> boom 1.\n')
            fake = compiler / "fpr"
            fake.write_text('''#!/usr/bin/env python3
import os, pathlib, re, sys
mode = os.environ['CASE']
args = ' '.join(sys.argv[1:])
if 'holes_named.fpr' in args:
    if mode != 'broken': print('typed hole, ?res : Int')
    sys.exit(0 if mode == 'unexpected-success' else 1)
if 'holes.sol' in args:
    if mode != 'broken': print('prefix ran, sum = 32\\nSOL PANIC: typed hole')
    sys.exit(124 if mode == 'timeout' else (139 if mode == 'crash' else 1))
if 'dispatch.sol' in args or 'handint.sol' in args:
    value = 'bad' if mode == 'mismatch' and os.environ.get('SOL_JIT') == '0' else 'good'
    if mode != 'empty': print('checksum ' + value)
    sys.exit(1 if mode == 'crash' else 0)
if 'txnabort.sol' in args:
    if mode == 'leak':
        path = re.search(r'@([^;]+)', pathlib.Path(sys.argv[-1]).read_text())[1]
        # Never let a broken harness fixture write outside this test directory.
        if not path.startswith(os.environ['CK_TMP'] + '/'):
            print('fixture path was not isolated', file=sys.stderr)
            sys.exit(2)
        pathlib.Path(path).write_text('partial write')
    if mode != 'crash': print('*** SOL PANIC: division by zero ***')
    sys.exit(124 if mode == 'timeout' else (0 if mode == 'unexpected-success' else 1))
sys.exit(2)
''')
            fake.chmod(0o755)
            final = (ROOT / "check-all.sh").read_text().splitlines()[-1]
            script = '''set -euo pipefail
ran() { "$@" || true; }
timeout() { shift; "$@"; }
make() {
    if [ "$CASE" != empty ]; then echo '3.5 3 1000'; fi
    [ "$CASE" != crash ]
}
''' + leg(prefix) + "\n" + final + "\n"
            result = subprocess.run(
                ["bash", "-c", script], cwd=root, capture_output=True, text=True,
                env=dict(os.environ, CK_TMP=temp, FPRISC_ROOT=str(compiler), CASE=mode),
                timeout=10)
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0 if success else 1, output)
            self.assertEqual((root / "ck-fail.flag").exists(), not success, output)
            self.assertIn("ALL LEGS GREEN" if success else "SWEEP HAS FAILURES", output)

    def test_float_build_and_output_are_both_required(self):
        for mode in ("ok", "crash", "empty"):
            with self.subTest(mode=mode):
                self.run_leg("Literal suffixes:", mode, mode == "ok")

    def test_holes_expected_refusals_pass_but_missing_diagnostics_fail(self):
        for mode in ("ok", "broken", "unexpected-success", "timeout", "crash"):
            with self.subTest(mode=mode):
                self.run_leg("typed holes:", mode, mode == "ok")

    def test_jit_requires_matching_output_and_successful_producers(self):
        for mode in ("ok", "mismatch", "empty", "crash"):
            with self.subTest(mode=mode):
                self.run_leg("native JIT tier", mode, mode == "ok")

    def test_transaction_requires_expected_panic_and_no_partial_write(self):
        for mode in ("ok", "leak", "crash", "timeout", "unexpected-success"):
            with self.subTest(mode=mode):
                self.run_leg("txn: the SCRIPT", mode, mode == "ok")


if __name__ == "__main__":
    unittest.main()
