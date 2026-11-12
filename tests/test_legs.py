"""Run real leg bodies from checks/legs against controlled successes and failures.

A leg's verdict is its body's exit status under checks/prelude.sh. These
cases check that the bodies themselves fail when a producer fails, times out
or prints nothing, and that an expected refusal is not taken for a failure.
The runner's own verdicts (counts, exit status, expected failures) are
checked by the `sweep verdicts` leg against checks/selftest.legs.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def leg(prefix):
    """The body of the leg whose name starts with `prefix`."""
    lines = (ROOT / "checks/legs").read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("== " + prefix))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("== ")), len(lines))
    return "\n".join(line for line in lines[start + 1:end] if not line.startswith("@ "))


def verdict(body, tree, compiler, env=None, before=""):
    """passed, skipped or failed: what checks/sweep.sol would record."""
    with tempfile.TemporaryDirectory(prefix="qos-leg-") as work:
        script = "\n".join([
            f". '{ROOT}/checks/prelude.sh'", before, "(", body, ")", "status=$?",
            'if [ $status -eq 0 ] && [ -e "$SWEEP_MARK.skipped" ]; then exit 77; fi',
            "exit $status", ""])
        result = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, timeout=30,
            env=dict(os.environ, SWEEP_TREE=str(tree), SWEEP_WORK=work, SWEEP_OUT=work,
                     SWEEP_COMPILER=str(compiler), SWEEP_MARK=work + "/mark", **(env or {})))
        name = {0: "passed", 77: "skipped"}.get(result.returncode, "failed")
        return name, result.stdout + result.stderr


class LegBodies(unittest.TestCase):
    def test_service_legs_read_their_own_verdicts(self):
        with tempfile.TemporaryDirectory(prefix="qos-service-verdict-") as temp:
            out = Path(temp)
            (out / "services").mkdir()
            (out / "services/results.json").write_text(json.dumps({"checks": {
                "files-service": {"status": "failed"}, "endpoint-state": {"status": "ok"}}}))
            for name, expected in (("files-service", "failed"), ("endpoint-state", "passed"), ("preferences", "failed")):
                script = f". '{ROOT}/checks/prelude.sh'\n(service_leg {name})\n"
                result = subprocess.run(
                    ["bash", "-c", script], capture_output=True, text=True, timeout=30,
                    env=dict(os.environ, SWEEP_TREE=str(ROOT), SWEEP_WORK=temp, SWEEP_OUT=temp,
                             SWEEP_COMPILER=temp, SWEEP_MARK=temp + "/mark"))
                self.assertEqual("passed" if result.returncode == 0 else "failed", expected, result.stdout + result.stderr)

    def test_native_instruction_gate_status_is_required(self):
        with tempfile.TemporaryDirectory(prefix="qos-native-gate-") as temp:
            compiler = Path(temp) / "compiler with spaces"
            (compiler / "tools").mkdir(parents=True)
            gate = compiler / "tools/native-insns-ratchet.py"
            source = '''import os,sys
assert sys.argv[1:] == ['programs/system.fpr','474','rv64','--runtime-call-sites-ceiling','95'],sys.argv
print('native-insns-v1 ratchet holds')
sys.exit({'ok':0,'regression':1,'timeout':124,'crash':139}[os.environ['CASE']])
'''
            for mode in ("ok", "regression", "timeout", "crash", "missing"):
                if mode == "missing":
                    gate.unlink()
                else:
                    gate.write_text(source)
                got, output = verdict(leg("Native instruction ratchet:"), temp, compiler, env={"CASE": mode})
                self.assertEqual(got, "passed" if mode == "ok" else "failed", output)

    def test_web_checks_distinguish_missing_dependency_and_failed_producer(self):
        with tempfile.TemporaryDirectory(prefix="qos-web-verdict-") as temp:
            root=Path(temp)
            for script in ("fprlive-check.sh","pos1-check.sh"):
                path=root/script
                path.write_text('#!/bin/sh\ncase "$CASE" in ok) echo "ALL LEGS PASS";; empty) exit 0;; crash) echo "ALL LEGS PASS"; exit 139;; broken) echo "wrong result";; esac\n')
                path.chmod(0o755)
            for prefix in ("FPRLive:","POS v1:"):
                body=leg(prefix).replace('qos/tests-host/',str(root)+'/')
                for mode in ("ok","missing","empty","crash","broken"):
                    with self.subTest(prefix=prefix,mode=mode):
                        got,output=verdict(body,root,root,env={"CASE":mode},before='python3() { [ "$CASE" != missing ]; }')
                        self.assertEqual(got,{"ok":"passed","missing":"skipped"}.get(mode,"failed"),output)

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
            before = '''timeout() { shift; "$@"; }
make() {
    if [ "$CASE" != empty ]; then echo '3.5 3 1000'; fi
    [ "$CASE" != crash ]
}'''
            got, output = verdict(leg(prefix), root, compiler, env={"CASE": mode}, before=before)
            self.assertEqual(got, "passed" if success else "failed", output)

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
