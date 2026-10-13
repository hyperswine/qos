#!/usr/bin/env python3
"""Exercise the real bootstrap's absence/error fallbacks with an offline store."""
import os
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
PROBE = '''
probeStore why me =
  (ret, _) = SVCM.requestFields (receive me);
  _ = SVCM.reply ret (Err why);
  probeStore why me.
probeCorrupt me =
  (ret, _) = SVCM.requestFields (receive me);
  _ = SVCM.reply ret (Ok "garbled decisions");
  probeCorrupt me.
probeErr r = case r of Err why -> why == "disk offline" | Ok value -> False.
probeCheck yes why = if yes then Unit else error "storagefallback: {why}".
main : unsafe String .
main =
  me = myself 0;
  offline = spawn (probeStore "disk offline");
  absent = spawn (probeStore "no such file");
  corrupt = spawn probeCorrupt;
  st = {has = True, act = offline, uart = 0, timer = 0};
  empty = {has = True, act = absent, uart = 0, timer = 0};
  io = Io4 (0, 0) me 0 st;
  _ = probeCheck (probeErr (permsStored io "TUINotes")) "permission read silently defaulted";
  _ = probeCheck (case permsStored (Io4 (0, 0) me 0 {has = True, act = corrupt, uart = 0, timer = 0}) "TUINotes" of Err why -> why == "malformed permission decisions" | Ok value -> False) "malformed decisions silently defaulted";
  _ = probeCheck (validPerms "y /services/files read\nn /pins/4 write\n" and not (validPerms "y  read\n")) "valid decision grammar";
  _ = probeCheck (probeErr (persistPerms1 io "TUINotes" Nil Nil Nil Nil)) "permission write silently accepted";
  _ = probeCheck (probeErr (qaFromDisk st me "TUINotes")) "offline archive fell back";
  _ = probeCheck (case qaFromDisk empty me "TUINotes" of Ok bytes -> strlen bytes > 0 | Err why -> False) "missing archive did not fall back";
  _ = probeCheck (case permsStored (Io4 (0, 0) me 0 empty) "TUINotes" of Ok "" -> True | other -> False) "missing decisions did not default";
  _ = probeCheck (case appsListDisk 0 (Err "disk offline") of Nil -> True | other -> False) "offline index fell back";
  "storagefallback: missing-only defaults, offline archives and permission read/write failures HOLDS".
'''
def run(command, cwd, env):
    p = subprocess.run(list(map(str, command)), cwd=cwd, env=env, capture_output=True, text=True, timeout=240)
    assert p.returncode == 0, p.stdout+p.stderr
    return p.stdout+p.stderr
with tempfile.TemporaryDirectory(prefix='qos-storage-fallback-') as tmp:
    out = Path(tmp)
    env = dict(os.environ, FPR_PORT='0', FPR_HARTS='4', XDG_CACHE_HOME=str(out/'cache'))
    with tempfile.NamedTemporaryFile(mode='w', suffix='.fpr', prefix='.storage-fallback-', dir=ROOT/'programs') as source:
        text = (ROOT/'programs/system.fpr').read_text()
        text = text.replace('main : unsafe Unit .', 'bootstrap : unsafe Unit .').replace('\nmain =', '\nbootstrap =')
        source.write("unsafe program.\n"+text+PROBE); source.flush()
        kernel = out/'fallback.elf'
        run(['make', '-s', '-C', 'qos', 'native', f'SYSTEM={source.name}', f'KERNEL={kernel}', f'BUILD={out/"build"}', 'HARTS=4'], ROOT, env)
        log = run(['qemu-system-riscv64', '-machine', 'virt', '-smp', '4', '-m', '256M', '-nographic', '-bios', 'none', '-kernel', kernel], out, env)
        assert 'storagefallback:' in log and 'HOLDS' in log, log
        print(log, end='')
