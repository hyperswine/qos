#!/usr/bin/env python3
"""Create an ignored, private Buildroot overlay for a Pi's Wi-Fi and SSH.

Reads SSID and PASSWORD as data, without executing .env shell code. Only
the derived WPA2 PSK is installed; no plaintext passphrase is written.
"""
import argparse
import base64
import hashlib
import os
import re
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def dotenv(path):
    values = {}
    for line in path.read_text().splitlines():
        match = re.fullmatch(r'\s*(?:export\s+)?(SSID|PASSWORD)\s*=\s*(.*?)\s*', line)
        if not match:
            continue
        key, value = match.groups()
        if key in values:
            raise ValueError(f'duplicate {key} setting')
        if value.startswith(('"', "'")):
            words = shlex.split(value, comments=True)
            if len(words) != 1:
                raise ValueError(f'invalid quoted {key} setting')
            value = words[0]
        else:
            value = value.split(' #', 1)[0].rstrip()
        values[key] = value
    if values.keys() != {'SSID', 'PASSWORD'}:
        raise ValueError('the .env file must define SSID and PASSWORD')
    return values


def provision(env_file, public_key, output, country='AU', hostname='qosp'):
    values = dotenv(env_file)
    ssid = values['SSID'].encode('utf-8')
    password = values['PASSWORD'].encode('utf-8')
    if not 1 <= len(ssid) <= 32:
        raise ValueError('SSID must contain 1 to 32 UTF-8 bytes')
    if re.fullmatch(rb'[0-9a-fA-F]{64}', password):
        psk = password.decode('ascii').lower()
    elif 8 <= len(password) <= 63:
        psk = hashlib.pbkdf2_hmac('sha1', password, ssid, 4096, 32).hex()
    else:
        raise ValueError('PASSWORD must be 8 to 63 bytes, or a 64-digit hex PSK')
    if not re.fullmatch(r'[A-Z]{2}', country):
        raise ValueError('country must be a two-letter uppercase code')
    if not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', hostname):
        raise ValueError('invalid hostname')
    key = public_key.read_text().strip()
    fields = key.split()
    if '\n' in key or len(fields) < 2 or fields[0] != 'ssh-ed25519':
        raise ValueError('supply one OpenSSH Ed25519 public key')
    blob = base64.b64decode(fields[1], validate=True)
    if len(blob) != 51 or blob[:19] != b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20':
        raise ValueError('invalid Ed25519 public key encoding')
    # Validate everything before writing. Reject links in private output paths.
    files = {
        'etc/wpa_supplicant.conf': (f'ctrl_interface=/run/wpa_supplicant\nupdate_config=0\ncountry={country}\n'
            f'network={{\n    ssid={ssid.hex()}\n    psk={psk}\n    key_mgmt=WPA-PSK\n    scan_ssid=1\n}}\n', 0o600),
        'root/.ssh/authorized_keys': (key + '\n', 0o600),
        'etc/hostname': (hostname + '\n', 0o644),
        'etc/ssh/sshd_config': ('PermitRootLogin prohibit-password\nPubkeyAuthentication yes\n'
            'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitEmptyPasswords no\n'
            'AuthorizedKeysFile .ssh/authorized_keys\nSubsystem sftp internal-sftp\n', 0o600),
    }
    for name in files:
        path = output / name
        for part in (path, *path.parents):
            if part.is_symlink():
                raise ValueError('overlay output must not contain symlinks')
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.chmod(0o700)
    for name, (contents, mode) in files.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        # Create with restrictive mode before placing any credential bytes.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(contents)
    (output / 'root').chmod(0o700)
    (output / 'root/.ssh').chmod(0o700)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env', type=Path, default=ROOT / '.env')
    parser.add_argument('--authorized-key', type=Path, default=Path.home() / '.ssh/id_ed25519.pub')
    parser.add_argument('--output', type=Path, default=ROOT / '.qos/pi4/overlay')
    parser.add_argument('--country', default='AU')
    parser.add_argument('--hostname', default='qosp')
    args = parser.parse_args()
    try:
        provision(args.env, args.authorized_key, args.output, args.country, args.hostname)
    except (OSError, ValueError) as error:
        # Parsing exceptions can contain input fragments. Never echo their text.
        parser.exit(1, f'Pi provisioning failed ({type(error).__name__}); check inputs and output permissions.\n')
    print('Private Pi overlay created; Wi-Fi settings withheld. SSH uses the supplied public key.')


if __name__ == '__main__':
    main()
