#!/usr/bin/env python3
"""inject.py -- drive the guest's USB keyboard and mouse through QMP.
   inject.py key h shift-h ret     press+release each (qcodes; mod-key for chords)
   inject.py rel 40 -12            relative mouse motion
   inject.py btn left              click"""
import json, socket, sys, time, os
os.chdir(os.environ.get("QOS_VM_DIR") or os.path.expanduser("~/.cache/qos-arm64-vm"))  # then a RELATIVE socket path: macOS caps AF_UNIX paths at 104 bytes
s = socket.socket(socket.AF_UNIX); s.connect("qmp.sock")
f = s.makefile("rw")
def cmd(c, **a):
    f.write(json.dumps({"execute": c, "arguments": a} if a else {"execute": c}) + "\n"); f.flush()
    while True:
        r = json.loads(f.readline())
        if "return" in r or "error" in r: return r
f.readline(); cmd("qmp_capabilities")
def key(q, down): return {"type": "key", "data": {"down": down, "key": {"type": "qcode", "data": q}}}
kind, args = sys.argv[1], sys.argv[2:]
if kind == "key":
    for a in args:
        parts = a.split("-"); mods, k = parts[:-1], parts[-1]
        for m in mods: cmd("input-send-event", events=[key(m, True)])
        cmd("input-send-event", events=[key(k, True)]); time.sleep(0.03); cmd("input-send-event", events=[key(k, False)])
        for m in reversed(mods): cmd("input-send-event", events=[key(m, False)])
        time.sleep(0.03)
elif kind == "rel":
    cmd("input-send-event", events=[{"type": "rel", "data": {"axis": "x", "value": int(args[0])}}, {"type": "rel", "data": {"axis": "y", "value": int(args[1])}}])
elif kind == "btn":
    for d in (True, False): cmd("input-send-event", events=[{"type": "btn", "data": {"down": d, "button": args[0]}}]); time.sleep(0.03)
