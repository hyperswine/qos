#!/usr/bin/env python3
"""Real Portable Sys.storeReq binary replay and durability-error mapping."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(args, cwd=ROOT, extra=None, timeout=240):
    p = subprocess.run(list(map(str, args)), cwd=cwd,
                       env={**os.environ, **(extra or {})}, capture_output=True,
                       text=True, timeout=timeout)
    text = p.stdout + p.stderr
    assert p.returncode == 0, (args, p.returncode, text)
    return text


SOURCE = '''unsafe program.
main =
  payload = strcat "A" (strcat (chr 0) (strcat (chr 10) "Z"));
  before = case Sys.storeReq 3 "" of Ok bytes -> bytes | Err why -> error why;
  _ = if before == "" then print "store: fresh" else
      if before == payload then print "store: binary replay" else error "unexpected prior payload";
  _ = case Sys.storeReq 2 payload of
    Ok ack -> if ack == "" then print "store: append Ok" else error "unexpected append reply"
    | Err why -> if why == "storage outcome unknown" then print "store: Err storage outcome unknown" else error why;
  after = case Sys.storeReq 3 "" of Ok bytes -> bytes | Err why -> error why;
  _ = if after == strcat before payload then print "store: binary round trip" else error "binary mismatch";
  "portable-store: PASS".
'''


with tempfile.TemporaryDirectory(prefix='qos-portable-store-') as name:
    tmp = Path(name)
    host, source, image = tmp / 'qosp', tmp / 'compatstore.fpr', tmp / 'compatstore.qa'
    source.write_text(SOURCE)
    run(['make', '-s', 'portable', f'QOSP_OUT={host}',
         'FPRBUILD_EXTRA=--cflag -DQOS_STORE_TEST'], cwd=ROOT / 'qos')
    run(['make', '-s', 'qos-app', f'PROG={source}', f'QA_OUT={image}', f'BUILD={tmp / "app"}'])

    def invoke(folder, fail=False):
        folder.mkdir(exist_ok=True)
        text = run([host, '--yes', image], cwd=folder, timeout=15,
                   extra={'FPR_HARTS': '2', 'FPR_PORT': '0',
                          'QOS_STORE_TEST_FAIL_SYNC_AT': '1' if fail else '0'})
        assert 'portable-store: PASS' in text and 'store: binary round trip' in text, text
        assert ('store: Err storage outcome unknown' if fail else 'store: append Ok') in text, text
        assert ('store: append Ok' not in text) if fail else ('store: Err' not in text), text
        files = list((folder / 'qos-store').glob('*.kv'))
        assert len(files) == 1, files
        return files[0], text

    expected = b'4\nA\0\nZ\n'
    work = tmp / 'success'
    path, text = invoke(work)
    assert 'store: fresh' in text and path.read_bytes() == expected, text
    path, text = invoke(work)
    assert 'store: binary replay' in text and path.read_bytes() == expected * 2, text
    print('Portable store: real Sys.storeReq binary append and fresh-process replay HOLDS', flush=True)

    work = tmp / 'flush-error'
    path, text = invoke(work, fail=True)
    assert 'store: fresh' in text and path.read_bytes() == expected, text
    path, text = invoke(work)
    assert 'store: binary replay' in text and path.read_bytes() == expected * 2, text
    print('Portable store: failed sync reaches FP-RISC as Err storage outcome unknown; fresh replay HOLDS', flush=True)

print('portable-store-check: PASS (host faults and fresh processes; physical power cuts untested)')
