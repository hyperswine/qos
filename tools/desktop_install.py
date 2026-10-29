"""Installed Main disk/profile policy above qos_disk's durable block format."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import qos_archive as qa
import qos_disk as disk


def compatible_sdk(sdk):
    meta = json.loads((sdk / 'sdk.json').read_text())
    qa.require(meta.get('architecture') == 'aarch64', 'installed desktop disk workflow currently supports AArch64 only')
    qa.require(meta.get('diskLockContract') == 1 and meta.get('profileApps'), 'SDK has no matching lock-capable Main profile; install the complete SDK')
    qa.require(meta.get('os') == sys.platform, 'SDK targets a different host OS')
    files = meta.get('profileFiles', {})
    for name, expected in files.items():
        p = sdk / 'profile' / name
        qa.require(p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == expected, f'profile {name} changed; reinstall matching SDK')
    qa.require('main.qa' in files, 'SDK has no verified Main entry archive')
    return meta


def parse(raw, meta, *, bundled=False, desktop=True):
    return qa.read(raw, meta['abi'], meta['architecture'], meta['desktopSession'], meta['desktopApi'], bundled=bundled, desktop=desktop)


def profile(meta):
    return {key: meta[key] for key in ('architecture', 'os', 'abi', 'desktopSession', 'desktopApi')} | {'format': 1, 'profile': 'Main'}


def index(raw):
    try:
        ids = raw.decode('ascii').splitlines()
    except UnicodeDecodeError:
        raise ValueError('invalid app catalogue encoding') from None
    qa.require(all(qa.valid_id(aid) for aid in ids) and len(set(ids)) == len(ids), 'invalid/duplicate app catalogue IDs')
    qa.require(raw == (''.join(aid + '\n' for aid in ids)).encode(), 'noncanonical app catalogue')
    return ids


def open_profile(fd, meta):
    current = disk.metadata(fd)
    latest = disk.scan(fd, current)
    qa.require(disk.PROFILE_KEY in latest and b'apps/index' in latest, 'disk lacks Main profile metadata; use qos disk create')
    marker = json.loads(latest[disk.PROFILE_KEY].read(fd))
    qa.require(marker == profile(meta), 'disk/profile compatibility mismatch; rebuild installed apps for the matching SDK before migrating this disk')
    ids = index(latest[b'apps/index'].read(fd))
    # Verify every discovered native archive before launching or updating;
    # refuse damaged/missing installed apps instead of silently losing tiles.
    trusted = {name[:-3]: sha for name, sha in meta['profileFiles'].items() if name != 'main.qa' and name.endswith('.qa')}
    for aid in ids:
        key = f'apps/{aid}.qa'.encode()
        qa.require(key in latest, f'catalogue references missing archive {aid}')
        raw = latest[key].read(fd)
        bundled = hashlib.sha256(raw).hexdigest() == trusted.get(aid)
        app = parse(raw, meta, bundled=bundled)
        qa.require(app.id == aid, 'catalogue/manifest ID mismatch')
    return current, latest, ids


def create(sdk, destination, size=32):
    meta = compatible_sdk(sdk)
    items, ids = [], []
    for name in meta['profileApps']:
        app = parse((sdk / 'profile' / name).read_bytes(), meta, bundled=True)
        qa.require(app.id not in ids, 'duplicate bundled app ID')
        ids.append(app.id)
        items.append((f'apps/{app.id}.qa'.encode(), app.raw))
    items.extend([(b'apps/index', ''.join(aid + '\n' for aid in ids).encode()),
                  (disk.PROFILE_KEY, json.dumps(profile(meta), sort_keys=True).encode())])
    disk.create(destination, size, items)
    print(f'Created Main disk {destination} ({len(ids)} apps)')


def install(sdk, archive, destination, checkpoint=lambda phase, detail: None):
    meta = compatible_sdk(sdk)
    app = parse(Path(archive).read_bytes(), meta)
    with disk.locked(destination) as fd:
        current, latest, ids = open_profile(fd, meta)
        changed = app.id in ids
        if not changed:
            ids.append(app.id)
        updated = disk.append(fd, current, [(f'apps/{app.id}.qa'.encode(), app.raw),
                                          (b'apps/index', ''.join(aid + '\n' for aid in ids).encode())], checkpoint)
    print(f'{"Updated" if changed else "Installed"} {app.id} {app.manifest["version"]} in {destination} (generation {updated.generation})')


def run(sdk, destination, extra_env=None):
    meta = compatible_sdk(sdk)
    entry = sdk / 'profile/main.qa'
    parse(entry.read_bytes(), meta, desktop=False, bundled=True)
    host = sdk / 'runtime/qosp-gl'
    expected = meta.get('runtimeFiles', {}).get('qosp-gl')
    qa.require(expected and host.is_file() and hashlib.sha256(host.read_bytes()).hexdigest() == expected,
               'matching prebuilt graphical host missing or changed; reinstall SDK')
    with disk.locked(destination) as fd:
        open_profile(fd, meta)
        # The host duplicates this SAME locked open-file description, verifies
        # the inode and holds it for its full lifetime. There is no handoff gap.
        env = dict(os.environ, **(extra_env or {}), FPR_DISK=str(Path(destination).resolve()), FPR_DISK_LOCK_FD=str(fd))
        return subprocess.call([str(host), '--yes', str(entry)], env=env, pass_fds=(fd,))
