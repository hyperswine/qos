#!/usr/bin/env python3
"""powercut-check.py -- cut the power to the appliance, many times.

Boots the Buildroot image hosting tests/powercut.fpr on a WORKING COPY of the
root filesystem, so the application's QLOG disk under /var/lib/qosp persists
across cycles exactly as an SD card would.  Each cycle:

  1. boot, log in, follow /var/log/qosp.log over the serial console
  2. wait for `powercut: recovered records=K last=L contiguous` and assert
     L >= the last record the previous cycle saw committed (nothing
     acknowledged is lost) and K == L (nothing in between is missing)
  3. let it commit for a random while, note the last `committed N` seen
  4. cut the power: `kill -9` of QEMU (even cycles), or of qosp inside the
     guest (odd cycles), which also exercises S99qosp's restart budget --
     in that case the recovery line comes from the restarted process

What a QEMU kill proves: the guest's file system and QLOG v3 ordering up to
the virtual device.  QEMU writes through to the host file at once and the
host survives, so a device that LIES about flushes is not modelled here; a
real SD card may.  `--cache unsafe` makes QEMU ignore the guest's flushes,
which is the closest approximation and is informative, not conclusive.

  ./powercut-check.py            20 cycles
  ./powercut-check.py --cycles 50 --cache directsync
"""
import os
import random
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.environ.get("QOSP_RUN_DIR", os.path.expanduser("~/.cache/qosp-br-run"))
BOOT_TIMEOUT = int(os.environ.get("QOSP_BOOT_TIMEOUT", "240"))


def arg(name, default):
    if name in sys.argv:
        return sys.argv[sys.argv.index(name) + 1]
    return default


class Console:
    def __init__(self, path, deadline):
        for _ in range(int(deadline * 10)):
            try:
                self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.s.connect(path)
                break
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(0.1)
        else:
            raise SystemExit(f"powercut: no serial socket at {path}")
        self.s.settimeout(0.2)
        self.buf = ""

    def pump(self):
        try:
            chunk = self.s.recv(65536)
            if chunk:
                self.buf += chunk.decode("utf-8", "replace")
        except socket.timeout:
            pass

    def expect(self, pattern, timeout, what):
        rx = re.compile(pattern)
        end = time.time() + timeout
        while time.time() < end:
            m = rx.search(self.buf)
            if m:
                self.buf = self.buf[m.end():]
                return m
            self.pump()
        raise SystemExit(f"powercut: timed out after {timeout}s waiting for {what}\n--- console ---\n{self.buf[-3000:]}")

    def send(self, line):
        self.s.sendall((line + "\n").encode())


def recovery(con, what):
    """The LAST recovery line in the log so far: the application started at
    boot, before we logged in, and the log may hold earlier boots' lines."""
    end = time.time() + 90
    while time.time() < end:
        mark = "__rec_%d__" % (time.monotonic_ns() % 1000000)
        con.send(f"grep 'powercut: recovered' /var/log/qosp.log | tail -1; echo {mark}")
        m = con.expect(re.escape(mark), 30, what)
        lines = re.findall(r"powercut: recovered records=(\d+) last=(-?\d+) (contiguous|GAP)", m.string[:m.start()])
        if lines:
            k, last, shape = lines[-1]
            return int(k), int(last), shape
        time.sleep(1.0)
    raise SystemExit(f"powercut: no recovery line within 90s ({what})\n{con.buf[-2000:]}")


def boot(image, rootfs, cache, run_dir):
    ser = os.path.join(run_dir, "console.sock")
    if os.path.exists(ser):
        os.unlink(ser)
    args = subprocess.run([os.path.join(HERE, "boot.sh"), "qemu-args"],
                          capture_output=True, text=True, check=True).stdout.splitlines()
    out = []
    for a in args:
        if a.startswith("-kernel"):
            out.append(a)
        elif a.startswith("file=") and "rootfs" in a:
            out.append(f"file={rootfs},if=none,format=raw,id=hd0,cache={cache}")
        elif a.startswith("user,id=n0"):
            out.append("user,id=n0")  # no host port forward: two loops may run at once
        else:
            out.append(a)
    i = out.index("-kernel")
    out[i + 1] = image
    out += ["-display", "none", "-serial", f"unix:{ser},server=on,wait=on"]
    err = open(os.path.join(run_dir, "qemu.err"), "ab")
    q = subprocess.Popen(["qemu-system-aarch64"] + out, stdout=subprocess.DEVNULL, stderr=err)
    return q, Console(ser, 30)


def main():
    cycles = int(arg("--cycles", "20"))
    cache = arg("--cache", "directsync")
    seed = int(arg("--seed", str(int(time.time()))))
    random.seed(seed)
    for f in ("Image", "rootfs.ext4"):
        if not os.path.exists(os.path.join(DIR, f)):
            raise SystemExit(f"powercut: no {f} in {DIR} -- run `boot.sh pull` first")
    run_dir = tempfile.mkdtemp(prefix="qosp-powercut-")
    rootfs = os.path.join(run_dir, "rootfs.ext4")
    shutil.copyfile(os.path.join(DIR, "rootfs.ext4"), rootfs)
    image = os.path.join(DIR, "Image")
    print(f"powercut: {cycles} cycles, cache={cache}, seed={seed}, working copy {rootfs}")

    last_committed = 0
    cuts = {"qemu": 0, "qosp": 0}
    for cycle in range(1, cycles + 1):
        q, con = boot(image, rootfs, cache, run_dir)
        try:
            con.expect(r"login:", BOOT_TIMEOUT, "the login prompt")
            con.send("root")
            con.expect(r"# ", 30, "a root shell")
            k, last, shape = recovery(con, "the recovery line")
            con.send("tail -n 0 -f /var/log/qosp.log")
            ok = shape == "contiguous" and last >= last_committed
            print(f"powercut: cycle {cycle}: recovered {k} records, last {last} ({shape}); "
                  f"previous cycle saw {last_committed} committed: {'HOLDS' if ok else 'LOST'}")
            if not ok:
                raise SystemExit(f"powercut: FAILED at cycle {cycle}: records={k} last={last} shape={shape} "
                                 f"committed-before-cut={last_committed}")
            m = con.expect(r"powercut: (committed (\d+)|append (\d+) failed: (.*))", 30, "the first commit")
            if m.group(3):
                print(f"powercut: cycle {cycle}: the disk is FULL after {last} records: append {m.group(3)} "
                      f"failed: {m.group(4).strip()} -- every record so far recovered; stopping here")
                q.kill(); q.wait()
                print(f"powercut: {cycle - 1} cycles HOLD, then the log filled (cache={cache}, seed={seed}); "
                      f"nothing acknowledged was lost")
                return
            time.sleep(random.uniform(0.5, 4.0))
            con.pump()
            seen = re.findall(r"powercut: committed (\d+)", con.buf)
            if seen:
                last_committed = max(last_committed, int(seen[-1]))
            if cycle % 2 == 1:
                cuts["qemu"] += 1
                q.kill()
                q.wait()
            else:
                cuts["qosp"] += 1
                # the serial shell is following the log: interrupt it, kill the application
                con.send("\x03")
                con.expect(r"# ", 10, "the shell back")
                con.send("kill -9 $(pidof qosp); echo __killed__")
                con.expect(r"__killed__", 10, "the kill")
                con.send("tail -n 0 -f /var/log/qosp.log")
                m = con.expect(r"powercut: recovered records=(\d+) last=(-?\d+) (contiguous|GAP)", 90,
                               "the restarted application's recovery line")
                k, last, shape = int(m.group(1)), int(m.group(2)), m.group(3)
                ok = shape == "contiguous" and last >= last_committed
                print(f"powercut: cycle {cycle}: after an in-guest kill the supervisor restarted it: "
                      f"{k} records, last {last} ({shape}): {'HOLDS' if ok else 'LOST'}")
                if not ok:
                    raise SystemExit(f"powercut: FAILED at cycle {cycle} after restart")
                con.expect(r"powercut: committed (\d+)", 30, "a commit after restart")
                time.sleep(random.uniform(0.5, 2.0))
                con.pump()
                seen = re.findall(r"powercut: committed (\d+)", con.buf)
                if seen:
                    last_committed = max(last_committed, int(seen[-1]))
                q.kill()
                q.wait()
        finally:
            if q.poll() is None:
                q.kill()
                q.wait()
    print(f"powercut: {cycles} cycles HOLD: {cuts['qemu']} machine cuts, {cuts['qosp']} in-guest kills with "
          f"supervisor restart, no acknowledged record lost, every log contiguous (cache={cache}, seed={seed})")
    shutil.rmtree(run_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
