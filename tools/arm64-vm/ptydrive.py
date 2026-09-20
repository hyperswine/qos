#!/usr/bin/env python3
"""ptydrive.py -- (runs IN the guest) host an app under qosp on a pseudo-terminal,
   type a fixed script of keys into it, resize it once, and print the app's
   `event k a c` lines.   ptydrive.py <app.qa> [keys|quiet]"""
import fcntl, os, pty, select, struct, sys, termios, time
qa, mode = sys.argv[1], (sys.argv[2:] or ["keys"])[0]
KEYS = [b"h", b"H", b"\x1b[A", b"\x1b[D", b"\r", b"\x1b", b"\x7f", b"\t", b"\x01", b"\x1bx",
        b"\x1b[1;5C", b"\x1b[3~", b"\x1bOP", b"\x1b[15~", b"\x1b[Z", b"?",
        b"\xc3\xa9", b"\x1b[<0;10;5M", b"z"]          # the last two before z name no key
pid, fd = pty.fork()
if pid == 0:
    os.chdir(os.path.expanduser("~/qos"))
    os.execv("./qos/qosp", ["qosp", "--yes", qa])
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
out, t0, sent, resized = b"", time.time(), 0, False
while time.time() - t0 < 11:
    if select.select([fd], [], [], 0.1)[0]:
        try: out += os.read(fd, 4096)
        except OSError: break
    if sent < len(KEYS) and time.time() - t0 > 2 + sent * 0.3:
        os.write(fd, KEYS[sent]); sent += 1       # typed in BOTH modes: `quiet` proves they are discarded
        if sent == 3 and not resized:
            resized = True
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
for line in out.decode(errors="replace").replace("\r", "").split("\n"):
    if line.startswith("event ") or line.startswith("[input]"): print(line)
