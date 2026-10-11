#!/usr/bin/env python3
"""pi-crash-check.py -- restart the appliance's application on a real Pi, many
times, and collect every fault it dies of.

The Pi runs the Buildroot image with S99qosp supervising qosp.  Each cycle:

  1. `/etc/init.d/S99qosp restart` (an administrative restart: it clears a
     latched failure too)
  2. wait until `status` says running (the application published readiness)
  3. watch /var/log/qosp.log for --watch seconds for `qosp: fatal SIGSEGV`
     (and the `fault lr= sp= x0=` line the current host prints after it) or
     `application N exited`, and record when, relative to readiness

With --install FILE the given qosp binary is put on the Pi first: the old
one is kept as /usr/bin/qosp.bak-<md5>, and restored by --restore.  With
--nm FILE (the output of `nm -n` on the UNSTRIPPED aarch64 qosp, which is
linked without PIE, so its addresses are the ones the fault prints) every
pc and lr is named with the symbol it falls in.

  ./pi-crash-check.py --host root@192.168.0.232 --cycles 20
  ./pi-crash-check.py --host root@192.168.0.232 --install qosp.rpi4 --nm qosp.nm --cycles 20
  ./pi-crash-check.py --host root@192.168.0.232 --restore
"""
import argparse
import bisect
import hashlib
import re
import subprocess
import sys
import time


def ssh(host, cmd, timeout=60):
    p = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, cmd],
                       capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def scp(src, host, dst):
    subprocess.run(["scp", "-o", "BatchMode=yes", src, f"{host}:{dst}"], check=True, timeout=120)


class Symbols:
    def __init__(self, path):
        self.addrs, self.names = [], []
        for line in open(path):
            parts = line.split()
            if len(parts) >= 3 and parts[1] in "tTwW":
                self.addrs.append(int(parts[0], 16)); self.names.append(parts[2])
        order = sorted(range(len(self.addrs)), key=lambda i: self.addrs[i])
        self.addrs = [self.addrs[i] for i in order]; self.names = [self.names[i] for i in order]

    def name(self, pc):
        if not pc or not self.addrs:
            return "?"
        i = bisect.bisect_right(self.addrs, pc) - 1
        if i < 0:
            return "?"
        return f"{self.names[i]}+{pc - self.addrs[i]:#x}"


def install(host, path):
    md5 = hashlib.md5(open(path, "rb").read()).hexdigest()
    rc, out, _ = ssh(host, "md5sum /usr/bin/qosp")
    if out.split()[0] == md5:
        print(f"pi-crash: the Pi already runs {md5[:12]}; nothing to install"); return
    print(f"pi-crash: installing {path} ({md5[:12]}) on {host}; the current binary is kept as a backup")
    scp(path, host, "/usr/bin/qosp.new")
    rc, out, err = ssh(host, "set -e; /etc/init.d/S99qosp stop >/dev/null 2>&1 || true; "
                             "old=$(md5sum /usr/bin/qosp | cut -c1-32); cp -p /usr/bin/qosp /usr/bin/qosp.bak-$old; "
                             "mv /usr/bin/qosp.new /usr/bin/qosp; chmod 755 /usr/bin/qosp; "
                             "echo backup=/usr/bin/qosp.bak-$old; md5sum /usr/bin/qosp", 120)
    print(out.strip())
    if rc != 0:
        raise SystemExit(f"pi-crash: install failed: {err}")


def restore(host):
    rc, out, err = ssh(host, "ls /usr/bin/qosp.bak-* 2>/dev/null | head -1")
    bak = out.strip()
    if not bak:
        raise SystemExit("pi-crash: no backup on the Pi")
    rc, out, err = ssh(host, f"/etc/init.d/S99qosp stop >/dev/null 2>&1 || true; cp -p {bak} /usr/bin/qosp; "
                             f"md5sum /usr/bin/qosp; /etc/init.d/S99qosp start", 120)
    print(out.strip(), err.strip())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True)
    ap.add_argument("--cycles", type=int, default=20)
    ap.add_argument("--watch", type=float, default=30.0, help="seconds to watch after readiness")
    ap.add_argument("--install")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--nm")
    a = ap.parse_args()
    if a.restore:
        restore(a.host); return
    if a.install:
        install(a.host, a.install)
    syms = Symbols(a.nm) if a.nm else None

    crashes, cycles_ok, exits = [], 0, []
    for cycle in range(1, a.cycles + 1):
        rc, out, _ = ssh(a.host, "wc -l < /var/log/qosp.log")
        before = int(out.strip() or 0)
        t0 = time.time()
        rc, out, err = ssh(a.host, "/etc/init.d/S99qosp restart 2>&1", 180)
        ready_at = None
        deadline = time.time() + 60
        while time.time() < deadline:
            rc, st, _ = ssh(a.host, "/etc/init.d/S99qosp status 2>&1")
            if "running" in st:
                ready_at = time.time(); break
            if "failed" in st:
                break
            time.sleep(0.5)
        if ready_at is None:
            rc, tail, _ = ssh(a.host, f"tail -n +{before + 1} /var/log/qosp.log | grep -a -E '^qosp: ' | tail -6")
            print(f"pi-crash: cycle {cycle}: never reached readiness ({st.strip()})\n    " + tail.strip().replace("\n", "\n    "))
            exits.append((cycle, "no-ready", st.strip()))
            continue
        ready_after = ready_at - t0
        fault = None
        end = ready_at + a.watch
        while time.time() < end:
            rc, new, _ = ssh(a.host, f"tail -n +{before + 1} /var/log/qosp.log | grep -a -E 'qosp: (fatal|fault|application .* exited)'")
            if new.strip():
                fault = (time.time() - ready_at, new.strip()); break
            time.sleep(1.0)
        if fault:
            dt, lines = fault
            m = re.search(r"pc=(0x[0-9a-f]+)", lines); lr = re.search(r"lr=(0x[0-9a-f]+)", lines)
            addr = re.search(r"addr=(0x[0-9a-f]+)", lines)
            pc_s = f" pc {syms.name(int(m.group(1), 16))}" if (m and syms) else ""
            lr_s = f" lr {syms.name(int(lr.group(1), 16))}" if (lr and syms) else ""
            print(f"pi-crash: cycle {cycle}: ready after {ready_after:.1f}s, FAULT {dt:.1f}s later:{pc_s}{lr_s}")
            for l in lines.splitlines(): print("    " + l)
            crashes.append((cycle, dt, addr.group(1) if addr else "?", m.group(1) if m else "?", lr.group(1) if lr else "?"))
        else:
            cycles_ok += 1
            print(f"pi-crash: cycle {cycle}: ready after {ready_after:.1f}s, no fault in {a.watch:.0f}s")
    print(f"pi-crash: {a.cycles} restarts: {cycles_ok} clean, {len(crashes)} faults, {len(exits)} never ready")
    if crashes:
        by = {}
        for c in crashes: by.setdefault((c[2], c[3], c[4]), []).append(c[1])
        for (addr, pc, lr), ts in by.items():
            where = f"  pc {syms.name(int(pc, 16))} lr {syms.name(int(lr, 16))}" if (syms and pc != "?" and lr != "?") else ""
            print(f"    addr={addr} pc={pc} lr={lr} x{len(ts)}, {min(ts):.1f}..{max(ts):.1f}s after readiness{where}")


if __name__ == "__main__":
    main()
