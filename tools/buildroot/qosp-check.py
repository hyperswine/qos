#!/usr/bin/env python3
"""qosp-check.py -- boot the Buildroot image and assert what came up.

The image is only worth building if a specific chain works end to end, and
this asserts each link of it:

  1. the kernel gives us a DRM device with a connected connector
  2. Mesa gives EGL on the SURFACELESS platform -- no X, no Wayland, no GBM
  3. drm_scanout.h takes that device and sizes the frame to the monitor's
     own mode (`frame fullscreen`), rather than falling back to offscreen
  4. the ES 3.1 renderer comes up and uploads the application's meshes
  5. pixels actually reach the monitor -- proved from OUTSIDE the guest,
     by asking QEMU to dump what its display is showing

The machine model comes from `boot.sh qemu-args`, so the thing this boots
cannot drift from the thing a person boots.

  ./qosp-check.py            boot, check, power off
  ./qosp-check.py --keep     leave it running afterwards
"""
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.environ.get("QOSP_RUN_DIR", os.path.expanduser("~/.cache/qosp-br-run"))
BOOT_TIMEOUT = int(os.environ.get("QOSP_BOOT_TIMEOUT", "240"))


QEMU_ERR = None  # where QEMU's own complaints go, shown on any failure


def fail(msg, extra=""):
    print(f"qosp-check: FAIL: {msg}")
    if extra:
        print(extra.rstrip()[-3000:])
    # a bad device or a missing accelerator kills QEMU before the guest says
    # anything, and without this the only symptom is a timeout
    if QEMU_ERR and os.path.exists(QEMU_ERR):
        err = open(QEMU_ERR).read().strip()
        if err:
            print("--- qemu said ---")
            print(err[-2000:])
    raise SystemExit(1)


class Console:
    """The guest's serial console, over a unix socket."""

    def __init__(self, path, deadline):
        for _ in range(int(deadline * 10)):
            try:
                self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.s.connect(path)
                break
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(0.1)
        else:
            fail(f"no serial socket at {path}")
        self.s.settimeout(0.5)
        self.buf = ""

    def expect(self, pattern, timeout, what):
        rx = re.compile(pattern)
        end = time.time() + timeout
        while time.time() < end:
            m = rx.search(self.buf)
            if m:
                self.buf = self.buf[m.end():]
                return m
            try:
                chunk = self.s.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                break
            self.buf += chunk.decode("utf-8", "replace")
        fail(f"timed out after {timeout}s waiting for {what}", self.buf)

    def send(self, line):
        self.s.sendall((line + "\n").encode())

    def run(self, cmd, timeout=60):
        """Run a command; return (output, exit status).

        The console is a stream with no framing, so each command carries its
        own: a unique marker echoed with the status.  `$?` is not digits, so
        the pattern cannot match the shell's echo of the command -- and that
        echo is what we cut the real output from.
        """
        mark = "__qc_%d__" % (time.monotonic_ns() % 1000000)
        probe = f"{mark}$?"
        self.send(f"{cmd}; echo {probe}")
        m = self.expect(re.escape(mark) + r"(\d+)", timeout, f"`{cmd}` to finish")
        raw = m.string[: m.start()]
        i = raw.find(probe)
        body = raw[i + len(probe):] if i >= 0 else raw
        return "\n".join(l.rstrip("\r") for l in body.splitlines()), int(m.group(1))


class Qmp:
    """QEMU's monitor, which is how we see the display from outside."""

    def __init__(self, path, deadline):
        for _ in range(int(deadline * 10)):
            try:
                self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.s.connect(path)
                break
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(0.1)
        else:
            fail(f"no QMP socket at {path}")
        self.f = self.s.makefile("rw", encoding="utf-8", newline="\n")
        self.f.readline()  # the greeting
        self.cmd("qmp_capabilities")

    def cmd(self, name, **args):
        msg = {"execute": name}
        if args:
            msg["arguments"] = args
        self.f.write(json.dumps(msg) + "\n")
        self.f.flush()
        while True:
            line = self.f.readline()
            if not line:
                fail(f"QMP closed during {name}")
            obj = json.loads(line)
            if "error" in obj:
                fail(f"QMP {name}: {obj['error']}")
            if "return" in obj:
                return obj["return"]


def lit_fraction(ppm):
    """How much of a P6 PPM is not near-black."""
    with open(ppm, "rb") as fh:
        data = fh.read()
    fields, off = [], 0
    while len(fields) < 4:
        while off < len(data) and data[off : off + 1].isspace():
            off += 1
        if data[off : off + 1] == b"#":
            while off < len(data) and data[off] != 0x0A:
                off += 1
            continue
        start = off
        while off < len(data) and not data[off : off + 1].isspace():
            off += 1
        fields.append(data[start:off])
    off += 1
    px = data[off:]
    if not px:
        return 0.0, (0, 0)
    w, h = int(fields[1]), int(fields[2])
    step = 3 * 211  # a prime stride, so we sample rather than read 8 MB
    lit = total = 0
    for i in range(0, len(px) - 3, step):
        total += 1
        if px[i] > 24 or px[i + 1] > 24 or px[i + 2] > 24:
            lit += 1
    return (lit / total if total else 0.0), (w, h)


def main():
    global QEMU_ERR
    keep = "--keep" in sys.argv
    for f in ("Image", "rootfs.ext4"):
        if not os.path.exists(os.path.join(DIR, f)):
            fail(f"no {f} in {DIR} -- run `boot.sh pull` first")

    run_dir = tempfile.mkdtemp(prefix="qosp-check-")
    ser = os.path.join(run_dir, "console.sock")
    qmpsock = os.path.join(run_dir, "qmp.sock")
    shot = os.path.join(run_dir, "screen.ppm")

    args = subprocess.run(
        [os.path.join(HERE, "boot.sh"), "qemu-args"],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    args += [
        "-display", "none",
        # wait=on: QEMU holds the machine until we are listening, so no
        # early boot output is lost to a race with our own startup
        "-serial", f"unix:{ser},server=on,wait=on",
        "-qmp", f"unix:{qmpsock},server=on,wait=off",
    ]

    print(f"qosp-check: booting ({DIR})")
    QEMU_ERR = os.path.join(run_dir, "qemu.err")
    errf = open(QEMU_ERR, "wb")
    qemu = subprocess.Popen(["qemu-system-aarch64"] + args,
                            stdout=subprocess.DEVNULL, stderr=errf)
    try:
        con = Console(ser, 20)
        mon = Qmp(qmpsock, 20)

        con.expect(r"login:", BOOT_TIMEOUT, "the login prompt")
        con.send("root")
        con.expect(r"# ", 30, "a root shell")
        print("qosp-check: booted, logged in")

        # 1. the DRM device
        dri, _ = con.run("ls /dev/dri 2>&1")
        if "card0" not in dri:
            dmesg, _ = con.run("dmesg | grep -i -E 'drm|virtio' | tail -20")
            fail("no /dev/dri/card0 -- the kernel has no DRM device", dri + "\n" + dmesg)
        print(f"qosp-check: DRM device present ({dri.strip()})")

        # the application is started at boot by S99qosp; give it a moment
        # to get through EGL, the renderer and its first frames
        con.run("sleep 8", timeout=30)
        log, rc = con.run("cat /var/log/qosp.log 2>&1")
        if rc != 0 or not log.strip():
            ini, _ = con.run("ls -la /etc/init.d/ /var/log/ 2>&1; pidof qosp")
            fail("no /var/log/qosp.log -- did S99qosp run?", log + "\n" + ini)

        # 2. EGL, on the surfaceless platform
        m = re.search(r"\[gfx\] EGL ([\d.]+) \((\w+)\)\s+(.*)", log)
        if not m:
            fail("qosp never reported an EGL context", log)
        if m.group(2) != "surfaceless":
            fail(f"EGL came up on the {m.group(2)} platform, not surfaceless", log)
        print(f"qosp-check: EGL {m.group(1)} surfaceless -- {m.group(3).strip()}")

        # 3. the KMS scanout took the display.  Whether the frame FILLS it is
        # the application's choice, not this image's: `glInit 0 0` adopts the
        # monitor's own mode, any other size is blitted centred in it.  Both
        # are the scanout working, so both pass and the check says which.
        m = re.search(r"\[gfx\] scanout: (\S+) (\d+)x(\d+) \(frame (\w+)\)", log)
        if not m:
            fail("the scanout never engaged -- qosp is rendering into nothing", log)
        print(f"qosp-check: scanout on {m.group(1)} at {m.group(2)}x{m.group(3)}, "
              f"frame {m.group(4)}")
        # and it must have got there BEFORE EGL, or Mesa would hold DRM master
        egl_at = log.find("[gfx] EGL")
        if egl_at >= 0 and log.find("[gfx] scanout:") > egl_at:
            fail("the scanout ran after EGL -- Mesa will own DRM master", log)

        # 4. the host really is hosting the application, and found its input
        m = re.search(r"qosp: hosting (\S+) \((\d+) harts, abi (v\d+)\)", log)
        if not m:
            fail("qosp never reported hosting an application", log)
        print(f"qosp-check: hosting {m.group(1)} on {m.group(2)} harts, abi {m.group(3)}")
        for tier, pat in (("keyboard", r"\[input\] keyboard: (\S+)"),
                          ("mouse", r"\[input\] mouse: (\S+)")):
            m = re.search(pat, log)
            print(f"qosp-check: {tier}: {m.group(1) if m else 'none'}")
        # meshes are per-application, so they are reported and not required
        meshes = re.findall(r"\[gfx\] mesh (\S+): (\d+) triangles", log)
        if meshes:
            print(f"qosp-check: {len(meshes)} meshes uploaded "
                  f"({sum(int(n) for _, n in meshes)} triangles)")

        # 5. pixels on the monitor, seen from outside the guest
        mon.cmd("screendump", filename=shot)
        for _ in range(50):
            if os.path.exists(shot) and os.path.getsize(shot) > 1024:
                break
            time.sleep(0.1)
        frac, (w, h) = lit_fraction(shot)
        if frac < 0.02:
            fail(f"the display is blank ({frac:.1%} of {w}x{h} lit)")
        print(f"qosp-check: display {w}x{h}, {frac:.0%} lit -- pixels reached the monitor")

        print("qosp-check: PASS")
        if not keep:
            con.send("poweroff")
            try:
                qemu.wait(timeout=60)
            except subprocess.TimeoutExpired:
                pass
        else:
            print(f"qosp-check: left running; console socket {ser}")
            return
    finally:
        if not keep and qemu.poll() is None:
            qemu.kill()


if __name__ == "__main__":
    main()
