#!/usr/bin/env python3
"""The fake compiler daemon for compile_check.c: fprd.py's framing, with
answers chosen by the request's profile line."""
import socket
import struct
import sys
import time

path = sys.argv[1]
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind(path)
server.listen(8)
print("ready", flush=True)
while True:
    conn, _ = server.accept()
    with conn:
        head = b""
        while len(head) < 4:
            part = conn.recv(4 - len(head))
            if not part:
                break
            head += part
        if len(head) < 4:
            continue
        (n,) = struct.unpack("<I", head)
        body = b""
        while len(body) < n:
            body += conn.recv(n - len(body))
        profile = body.split(b"\n", 1)[0]
        if profile == b"silent":
            time.sleep(4)        # past the check build's 2 s wait: say nothing
            continue
        if profile == b"slow":
            time.sleep(0.5)
        reply = b"ok\n" + b"x" * (1 << 20)
        try:
            conn.sendall(struct.pack("<I", len(reply)) + reply)
        except OSError:
            pass
