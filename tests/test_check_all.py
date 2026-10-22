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
    def run_sweep_file(self, body, env=None):
        """Run legs plus the real summary block as a script file, so its
        `grep "$0"` leg count sees three legs rather than a bash -c string."""
        with tempfile.TemporaryDirectory(prefix="qos-sweep-summary-") as temp:
            lines = (ROOT / "check-all.sh").read_text().splitlines()
            start = next(i for i, line in enumerate(lines)
                         if line.startswith("# ---- sweep summary"))
            script = "\n".join([
                "set -euo pipefail",
                'leg_failed() { echo "** LEG FAILED";'
                ' printf "%s\\n" "${1:-?}" >> "${CK_TMP}/ck-fail.lines";'
                ' : > "${CK_TMP}/ck-fail.flag"; }',
                'leg_skipped() { echo "skipped ($1)";'
                ' printf "%s\\n" "$1" >> "${CK_TMP}/ck-skip.lines"; }',
                body,
                "\n".join(lines[start:]),
                "",
            ])
            path = Path(temp) / "sweep.sh"
            path.write_text(script)
            return subprocess.run(
                ["bash", str(path)], cwd=temp, capture_output=True, text=True,
                env=dict(os.environ, CK_TMP=temp, **(env or {})), timeout=10)

    def test_summary_counts_pass_fail_and_skip(self):
        result = self.run_sweep_file(
            'echo "== pass ==" && true || leg_failed "${LINENO:-?}"\n'
            'echo "== fail ==" && false || leg_failed "${LINENO:-?}"\n'
            'echo "== skip ==" && (leg_skipped "no tool") || leg_failed "${LINENO:-?}"\n')
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("SWEEP: 1 passed, 1 failed, 1 skipped (of 3 legs)", output)
        self.assertIn("SWEEP HAS FAILURES", output)

    def test_a_skip_is_visible_and_strict_mode_fails(self):
        body = ('echo "== pass ==" && true || leg_failed "${LINENO:-?}"\n'
                'echo "== skip ==" && (leg_skipped "no tool") || leg_failed "${LINENO:-?}"\n')
        result = self.run_sweep_file(body)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("SWEEP: 1 passed, 0 failed, 1 skipped (of 2 legs)", output)
        self.assertIn("which is not a pass", output)
        self.assertIn("ALL RUNNABLE LEGS GREEN (1 SKIPPED, NOT RUN)", output)
        self.assertNotIn("ALL LEGS GREEN", output)
        strict = self.run_sweep_file(body, env={"QOS_SWEEP_STRICT": "1"})
        strict_output = strict.stdout + strict.stderr
        self.assertEqual(strict.returncode, 1, strict_output)
        self.assertIn("SWEEP HAS SKIPPED LEGS", strict_output)

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
            final = (ROOT / "check-all.sh").read_text().splitlines()
            start = next(i for i, line in enumerate(final)
                         if line.startswith("# ---- sweep summary"))
            final = "\n".join(final[start:])
            script = '''set -euo pipefail
ran() { "$@" || true; }
leg_failed() {
    echo "** LEG FAILED"
    printf '%s\\n' "${1:-?}" >> "${CK_TMP}/ck-fail.lines"
    : > "${CK_TMP}/ck-fail.flag"
}
leg_skipped() {
    echo "skipped ($1)"
    printf '%s\\n' "$1" >> "${CK_TMP}/ck-skip.lines"
}
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
