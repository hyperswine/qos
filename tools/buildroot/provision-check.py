#!/usr/bin/env python3
"""Check Pi provisioning with synthetic inputs, never the real .env."""
import base64
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

SCRIPT = Path(__file__).with_name('provision-pi.py')
spec = importlib.util.spec_from_file_location('provision', SCRIPT)
provision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provision)

with tempfile.TemporaryDirectory(prefix='qosp-pi-provision-') as name:
    # macOS aliases /var to /private/var; use the physical fixture directory.
    root = Path(name).resolve()
    env, key = root / 'input.env', root / 'key.pub'
    blob = b'\0\0\0\x0bssh-ed25519\0\0\0\x20' + bytes(range(32))
    key.write_text('ssh-ed25519 ' + base64.b64encode(blob).decode() + ' fixture\n')
    env.write_text('SSID=IEEE\nPASSWORD=password\n')
    output = root / 'overlay'
    provision.provision(env, key, output)
    config = (output / 'etc/wpa_supplicant.conf').read_text()
    # Published WPA2 PBKDF2 test vector, independent of this implementation.
    assert 'f42c6fc52df0ebef9ebb4b90b38a5f902e83fe1b135a70e23aed762e9710a12e' in config
    assert 'password' not in config
    for filename in ('etc/wpa_supplicant.conf', 'root/.ssh/authorized_keys', 'etc/ssh/sshd_config'):
        assert (output / filename).stat().st_mode & 0o777 == 0o600
    assert (output / 'root/.ssh').stat().st_mode & 0o777 == 0o700
    marker = Path('/tmp').resolve() / f'qpi-{os.getpid()}'
    assert not marker.exists()
    env.write_text(f'export SSID="quoted # network"\nPASSWORD=\'$(touch {marker})\'\n')
    provision.provision(env, key, root / 'literal')
    assert not marker.exists()
    env.write_text('SSID=IEEE\nPASSWORD=' + 'ab' * 32 + '\n')
    provision.provision(env, key, root / 'psk')
    assert 'psk=' + 'ab' * 32 in (root / 'psk/etc/wpa_supplicant.conf').read_text()
    env.write_text('SSID=IEEE\nPASSWORD="sensitive-invalid-quote\n')
    result = subprocess.run(['python3', str(SCRIPT), '--env', str(env), '--authorized-key', str(key),
        '--output', str(root / 'invalid')], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'sensitive-invalid-quote' not in result.stdout + result.stderr
    assert not (root / 'invalid').exists()
    env.write_text('SSID=IEEE\nPASSWORD=password\n')
    (root / 'link').symlink_to(output, target_is_directory=True)
    try:
        provision.provision(env, key, root / 'link')
    except ValueError:
        pass
    else:
        raise AssertionError('symlink accepted')

print('Pi provisioning: WPA2 vector, quoting, raw PSK, modes, redacted errors and link refusal passed.')
