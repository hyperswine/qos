#!/usr/bin/env python3
"""Real C block tier versus Python offline owner, including inherited lock handoff."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qos_disk as disk

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='qos-disk-lock-') as td:
        work = Path(td)
        source, binary = work / 'main.c', work / 'check'
        source.write_text('''#include "blk_raw.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdarg.h>
void qos_hostlog(const char *fmt, ...) {
 va_list ap;va_start(ap,fmt);vfprintf(stderr,fmt,ap);fputc('\\n',stderr);va_end(ap);
}
int main(int argc, char **argv) {
 long long pages=(long long)qos_blkraw_pages();
 printf("pages=%lld\\n",pages);fflush(stdout);
 if (pages<=0) return 75;
 if (getenv("FPR_DISK_LOCK_FD")) return 76;
 if (argc>1 && !strcmp(argv[1],"hold")) getchar();
 return 0;
}
''')
        subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror', '-I' + str(ROOT / 'hal/unix'), str(source),
                        str(ROOT / 'hal/unix/blk_raw.c'), '-lpthread', '-o', str(binary)], check=True)
        path = work / 'disk'
        path.write_bytes(bytes(disk.PAGE * 4))
        alias = work / 'alias'
        os.link(path, alias)
        env = {k: v for k, v in os.environ.items() if k != 'FPR_DISK_LOCK_FD'} | {'FPR_DISK': str(path)}
        with disk.locked(path) as fd:
            for other in (path, alias):
                child = subprocess.run([str(binary)], env=dict(env, FPR_DISK=str(other)), capture_output=True, timeout=5)
                assert child.returncode == 75 and b'in use' in child.stderr, child
            # Same description can be inherited by a child without unlocking.
            child = subprocess.run([str(binary)], env=dict(env, FPR_DISK_LOCK_FD=str(fd)),
                                   pass_fds=(fd,), capture_output=True, timeout=5)
            assert child.returncode == 0 and b'pages=4' in child.stdout, child
            # A different inode is refused, and neither backing file is changed.
            other = work / 'other'
            other.write_bytes(bytes(disk.PAGE * 4))
            child = subprocess.run([str(binary)], env=dict(env, FPR_DISK_LOCK_FD=str(fd), FPR_DISK=str(other)),
                                   pass_fds=(fd,), capture_output=True, timeout=5)
            assert child.returncode == 75 and b'invalid inherited' in child.stderr, child
        with disk.locked(path) as fd:
            inherited = subprocess.Popen([str(binary), 'hold'], env=dict(env, FPR_DISK_LOCK_FD=str(fd)),
                                         pass_fds=(fd,), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            assert inherited.stdout.readline() == b'pages=4\n'
        # Parent descriptor is now closed; the host must retain ownership.
        try:
            try:
                with disk.locked(path):
                    raise AssertionError('inherited host lost lock when CLI closed')
            except ValueError as error:
                assert 'in use' in str(error)
        finally:
            inherited.communicate(b'\n', timeout=5)
        assert inherited.returncode == 0
        native = subprocess.Popen([str(binary), 'hold'], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            assert native.stdout.readline() == b'pages=4\n'
            for other in (path, alias):
                try:
                    with disk.locked(other):
                        raise AssertionError('Python installer bypassed native host lock')
                except ValueError as error:
                    assert 'in use' in str(error), error
            child = subprocess.run([str(binary)], env=env, capture_output=True, timeout=5)
            assert child.returncode == 75 and b'in use' in child.stderr, child
        finally:
            native.communicate(b'\n', timeout=5)
        assert native.returncode == 0
        # Closing either owner releases the lock for the next process.
        with disk.locked(path):
            pass
        assert path.read_bytes() == bytes(disk.PAGE * 4)
    print('desktop disk lock: C/Python exclusion, inode aliases, inherited handoff and release HOLDS')


if __name__ == '__main__':
    main()
