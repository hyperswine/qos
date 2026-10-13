#!/usr/bin/env python3
"""Boot STAR64 Linux/rootfs under QEMU virt; this does not emulate STAR64 hardware."""
import argparse
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import tempfile
import time


def send_console_text(port, text):
    """Inject keystrokes through QEMU's USB keyboard, not the serial console."""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        stream = connection.makefile("rwb", buffering=0)
        json.loads(stream.readline())  # QMP greeting

        def execute(name, arguments=None):
            request = {"execute": name}
            if arguments is not None:
                request["arguments"] = arguments
            stream.write(json.dumps(request).encode() + b"\n")
            while True:
                response = json.loads(stream.readline())
                if "error" in response:
                    raise RuntimeError(response["error"])
                if "return" in response:
                    return

        execute("qmp_capabilities")
        for character in text:
            key = {" ": "spc", "\n": "ret", "/": "slash"}.get(character, character)
            execute("input-send-event", {"events": [
                {"type": "key", "data": {"down": True, "key": {"type": "qcode", "data": key}}},
                {"type": "key", "data": {"down": False, "key": {"type": "qcode", "data": key}}},
            ]})
            time.sleep(0.05)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", type=Path)
    parser.add_argument("--qemu", default="qemu-system-riscv64")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--ssh-identity", type=Path,
                        help="Authenticate as root with this host SSH identity; private material stays with the SSH client")
    parser.add_argument("--console-login", action="store_true",
                        help="Test tty1 root login and command input through an emulated USB keyboard")
    args = parser.parse_args()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        ssh_port = listener.getsockname()[1]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        qmp_port = listener.getsockname()[1]
    command = [args.qemu, "-machine", "virt", "-cpu", "rv64", "-m", "2G", "-smp", "2",
               "-kernel", str(args.images / "Image"), "-append",
               "root=/dev/vda rootwait rw console=ttyS0,115200 earlycon=sbi",
               "-drive", f"file={args.images / 'rootfs.ext4'},format=raw,if=none,id=root",
               "-device", "virtio-blk-device,drive=root",
               "-snapshot", "-netdev", f"user,id=n0,hostfwd=tcp:127.0.0.1:{ssh_port}-:22",
               "-device", "virtio-net-device,netdev=n0",
               "-device", "virtio-rng-device", "-display", "none", "-serial", "stdio",
               "-monitor", "none", "-no-reboot"]
    if args.console_login:
        command += ["-device", "virtio-gpu-pci", "-device", "qemu-xhci,id=usb",
                    "-device", "usb-kbd,bus=usb.0",
                    "-qmp", f"tcp:127.0.0.1:{qmp_port},server=on,wait=off"]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT)
    deadline = time.monotonic() + args.timeout
    output = b""
    stage = 0
    success = False
    # Exit-status checks are executed in the guest's actual RISC-V userspace.
    guest_command = (
        "test $(uname -m) = riscv64 && LIBGL_ALWAYS_SOFTWARE=1 star64-egl-check && "
        "/usr/sbin/sshd -t && ip -4 addr show eth0 | grep 'inet ' && "
    )
    if args.console_login:
        guest_command += (
            "grep -q 'QEMU USB Keyboard' /proc/bus/input/devices && "
            "test -f /run/hdmilogin && echo STAR64_USB_CONSOLE_PASS && "
        )
    if args.ssh_identity:
        guest_command += (
            "ls -ldn /root/.ssh /root/.ssh/authorized_keys | awk '"
            '$1=="drwx------" && $3==0 && $4==0 && $NF=="/root/.ssh" {dir=1} '
            '$1=="-rw-------" && $3==0 && $4==0 && $NF=="/root/.ssh/authorized_keys" {key=1} '
            "END {exit !(dir && key)}' && "
            "ssh-keygen -lf /root/.ssh/authorized_keys && "
        )
    guest_command += "echo STAR64_CHECK_PASS; poweroff\n"
    args.log.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.log.open("wb") as log, tempfile.TemporaryDirectory(prefix="star64-ssh-check-") as scratch:
            while time.monotonic() < deadline:
                readable, _, _ = select.select([process.stdout], [], [], 1)
                if not readable:
                    if process.poll() is not None:
                        break
                    continue
                block = os.read(process.stdout.fileno(), 65536)
                if not block:
                    break
                log.write(block)
                log.flush()
                output += block
                if stage == 0 and b"login:" in output:
                    # Test the guest's actual SSH listener.
                    with socket.create_connection(("127.0.0.1", ssh_port), timeout=5) as connection:
                        banner = connection.makefile("rb").readline(256)
                    if not banner.startswith(b"SSH-2.0-OpenSSH_"):
                        raise SystemExit(f"FAIL unexpected SSH banner: {banner!r}")
                    log.write(b"\nSSH listener check: " + banner)
                    log.flush()
                    if args.ssh_identity:
                        result = subprocess.run([
                            "ssh", "-F", "/dev/null", "-T", "-p", str(ssh_port),
                            "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                            "-o", "IgnoreUnknown=UseKeychain", "-o", "UseKeychain=yes",
                            "-o", "StrictHostKeyChecking=accept-new",
                            "-o", f"UserKnownHostsFile={scratch}/known_hosts",
                            "-i", str(args.ssh_identity), "root@127.0.0.1",
                            'test "$(uname -m)" = riscv64 && echo STAR64_SSH_AUTH_PASS',
                        ], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=30)
                        log.write(result.stdout)
                        log.flush()
                        if result.returncode or b"STAR64_SSH_AUTH_PASS" not in result.stdout:
                            raise SystemExit(f"FAIL authenticated SSH check; see {args.log}")
                    if args.console_login:
                        send_console_text(qmp_port, "root\n")
                        time.sleep(1)
                        send_console_text(qmp_port, "touch /run/hdmilogin\n")
                    process.stdin.write(b"root\n")
                    process.stdin.flush()
                    output = b""
                    stage = 1
                elif stage == 1 and (b"# " in output or b"#\r" in output):
                    process.stdin.write(guest_command.encode())
                    process.stdin.flush()
                    output = b""
                    stage = 2
                elif stage == 2 and b"\nSTAR64_CHECK_PASS\r" in output:
                    success = True
                if b"Kernel panic" in output:
                    break
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    if not success:
        raise SystemExit(f"FAIL emulated boot/userspace check; see {args.log}")
    extra = ", authenticated SSH" if args.ssh_identity else ""
    if args.console_login:
        extra += ", tty1 login through USB keyboard"
    print(f"PASS RV64 Linux boot, software EGL readback, SSH listener/configuration and emulated Ethernet DHCP{extra}; log: {args.log}")


if __name__ == "__main__":
    main()
