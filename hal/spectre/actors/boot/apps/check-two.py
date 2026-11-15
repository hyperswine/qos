"""Exercise two named, independently compiled apps on the Spectre UART."""
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ["SIMPLE_RISC"]) / "boards/tangnano20k"))
from run_program import open_port
from rom_protocol import FdTransport

port = os.environ.get("SPECTRE_UART", "/dev/cu.usbserial-20250303171")
fd = open_port(port, round(54e6 / 868))
uart = FdTransport(fd)


def command(line):
    for byte in (line + "\n").encode():
        uart.write(bytes([byte]))
        time.sleep(0.006)
    frame = uart.read_until(lambda data: b"qos> " in data, 15)
    before, prompt, _ = frame.partition(b"qos> ")
    assert prompt, frame
    rows = before.decode().splitlines()
    shown = line.split(" ", 2)[:2] if line.startswith("create ") else line
    print(shown, rows[-1][:90] if rows else "", flush=True)
    return rows


def expect(line, reply):
    assert reply in command(line), (line, reply)


def yields(slot):
    rows = command(f"status {slot}")
    return int(next(row.split()[-1] for row in rows if re.fullmatch(r"running; yields \d+", row)))


def check_mailbox():
    for app in ("pong", "ping"):
        name = f"apps/{app}.sxa"
        image = Path(f"{app}.sxa").read_text()
        rows = command(f"create {name} {image}")
        assert f"created {name}" in rows or "already exists" in rows
        expect(f"cat {name}", image)
    for _ in range(2):
        expect("run apps/pong.sxa", "started job 1")
        assert yields(1) == 0
        expect("cat notes/spectre.txt", "hello from Spectre")
        expect("run apps/ping.sxa", "started job 2")
        expect("status 1", "exit 37")
        expect("status 2", "exit 37")
        expect("cat notes/spectre.txt", "hello from Spectre")


def check_two():
    for app in ("spin", "pendulum", "hello"):
        name = "apps/hello2.sxa" if app == "hello" else f"apps/{app}.sxa"
        image = Path(f"{app}.sxa").read_text()
        rows = command(f"create {name} {image}")
        assert f"created {name}" in rows or "already exists" in rows
        expect(f"cat {name}", image)
    expect("run apps/spin.sxa", "started job 1")
    expect("run apps/pendulum.sxa", "started job 2")
    first, second = yields(1), yields(2)
    expect("run apps/hello2.sxa", "run: busy")
    expect("cat notes/spectre.txt", "hello from Spectre")
    assert yields(1) > first and yields(2) > second
    expect("stop 1", "stopped")
    expect("status 1", "stopped")
    second = yields(2)
    expect("run apps/hello2.sxa", "started job 1")
    time.sleep(0.2)
    expect("status 1", "exit 42")
    assert yields(2) > second
    expect("stop 2", "stopped")
    expect("status 2", "stopped")
    expect("cat notes/spectre.txt", "hello from Spectre")


try:
    command("")
    if sys.argv[1:] == ["--mailbox"]:
        check_mailbox()
    elif not sys.argv[1:]:
        check_two()
    else:
        raise SystemExit("expected optional --mailbox")
    print("PASS")
finally:
    os.close(fd)
