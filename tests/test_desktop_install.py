"""Disk installer contract and crash/fault boundaries, using tiny native fixtures.

The synthetic image is deliberately never executed. Real compiled archives and
Main are exercised separately by portable-sdk-check.py.
"""
import errno
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import desktop_install as install
import qos_archive as archive
import qos_disk as disk


def fixture_image(arity=1):
    image = bytearray(512)
    struct.pack_into('<7Q', image, 0, 0x4650524D, 1, 80, 80, 112, 192, 144)
    for at, text in ((80, b'root'), (112, b'appMain'), (144, b'')):
        struct.pack_into('<IIQ', image, at, 9000, 0, len(text))
        image[at + 16:at + 16 + len(text)] = text
    struct.pack_into('<II3Q', image, 192, 9001, 0, 256, arity, 0)
    return bytes(image)


def pack(parts):
    offset, rows = 0, []
    for name, value in parts.items():
        rows.append(f'{name} {offset} {len(value)}\n'.encode())
        offset += len(value)
    return b'QAR2\n' + b''.join(rows) + b'\n' + b''.join(parts.values())


def app(aid='counter', version='1', *, process=False, arity=1, **overrides):
    manifest = dict(id=aid, name='Counter', version=version, abi='22.137', architecture='aarch64',
                    desktopSession='qos.app-session/4', desktopApi='qos.desktop/1',
                    loadMode='process' if process else 'plugin', entry='n/a' if process else 'fpr_modtab')
    manifest.update(overrides)
    image = fixture_image(arity)
    reloc = struct.pack('<6I', 16, 24, 32, 40, 48, 200)
    load = (f'base 0\nentry 0\nexecsz 320\nrwoff 512\nimagesz 512\nmemsz 512\n'
            f'sha {hashlib.sha256(image).hexdigest()}\nrelsha {hashlib.sha256(reloc).hexdigest()}\n').encode()
    return pack(dict(MANIFEST=''.join(f'{key} = {json.dumps(value)}\n' for key, value in manifest.items()).encode(),
                     LOAD=load, IMAGE=image, RELOC=reloc, IMPORT=b''))


class Installer(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.sdk = self.base / 'sdk'
        (self.sdk / 'profile').mkdir(parents=True)
        main, seed = app('main', process=True), app('seed')
        (self.sdk / 'profile/main.qa').write_bytes(main)
        (self.sdk / 'profile/seed.qa').write_bytes(seed)
        self.meta = dict(architecture='aarch64', os=sys.platform, abi='22.137', desktopSession='qos.app-session/4',
                         desktopApi='qos.desktop/1', diskLockContract=1, profileApps=['seed.qa'],
                         profileFiles={'main.qa': hashlib.sha256(main).hexdigest(), 'seed.qa': hashlib.sha256(seed).hexdigest()})
        (self.sdk / 'sdk.json').write_text(json.dumps(self.meta))
        self.path = self.base / 'main.disk'
        install.create(self.sdk, self.path, size=1)
        self.qa = self.base / 'renamed-output.qa'
        self.qa.write_bytes(app())
        install.install(self.sdk, self.qa, self.path)
        with disk.locked(self.path) as fd:
            disk.append(fd, disk.metadata(fd), [(b'user/note', b'preserve\0binary\xff'), (b'apps/custom/user', b'also keep')])
        self.original = self.path.read_bytes()
        with disk.locked(self.path) as fd:
            self.old_meta = disk.metadata(fd)
        self.qa.write_bytes(app(version='2'))

    def values(self, path=None):
        with disk.locked(path or self.path) as fd:
            meta = disk.metadata(fd)
            return meta, {key: val.read(fd) for key, val in disk.scan(fd, meta).items()}

    def test_manifest_id_update_and_history_preserved(self):
        _, before = self.values()
        install.install(self.sdk, self.qa, self.path)
        meta, after = self.values()
        self.assertEqual(after[b'apps/index'], b'seed\ncounter\n')
        self.assertEqual(after[b'apps/counter.qa'], self.qa.read_bytes())
        for key, value in before.items():
            if key != b'apps/counter.qa':
                self.assertEqual(after[key], value)
        self.assertEqual(self.path.read_bytes()[disk.PAGE:self.old_meta.head * disk.PAGE],
                         self.original[disk.PAGE:self.old_meta.head * disk.PAGE])
        self.assertEqual(meta.generation, self.old_meta.generation + 1)
        # Both slots are valid: the fallback exposes the complete old version.
        with disk.locked(self.path) as fd:
            fallback = disk.parse_seal(os.pread(fd, disk.PAGE, 0 if meta.generation % 2 else len(self.original) - disk.PAGE), len(self.original) // disk.PAGE)
            self.assertEqual(disk.scan(fd, fallback)[b'apps/counter.qa'].read(fd), app())

    def test_no_clobber_create(self):
        with self.assertRaisesRegex(ValueError, 'already exists'):
            install.create(self.sdk, self.path)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_incompatible_or_corrupt_archive_refused_without_writes(self):
        cases = [app(architecture='x86_64'), app(abi='22.1'), app(desktopSession='old'), app(desktopApi='old'),
                 app(aid='../escape'), app(process=True), app(arity=2), b'not a QAR2 archive']
        broken = bytearray(app())
        broken[-20] ^= 1
        cases.append(bytes(broken))
        for payload in cases:
            with self.subTest(payload=payload[:35]):
                self.qa.write_bytes(payload)
                with self.assertRaises(ValueError):
                    install.install(self.sdk, self.qa, self.path)
                self.assertEqual(self.path.read_bytes(), self.original)

    def test_torn_or_mismatched_profile_refused(self):
        with disk.locked(self.path) as fd:
            disk.append(fd, disk.metadata(fd), [(disk.PROFILE_KEY, b'{}')])
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'compatibility mismatch'):
            install.install(self.sdk, self.qa, self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_full_disk_refused_before_writing(self):
        with disk.locked(self.path) as fd:
            meta = disk.metadata(fd)
            os.pwrite(fd, disk.replace(meta, data_end=meta.head, swap=meta.head).page(),
                      0 if meta.generation % 2 == 0 else len(self.original) - disk.PAGE)
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'full'):
            install.install(self.sdk, self.qa, self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_lock_covers_aliases_and_concurrent_installer(self):
        alias = self.base / 'hardlink.disk'
        os.link(self.path, alias)
        with disk.locked(self.path):
            for path in (self.path, alias):
                with self.assertRaisesRegex(ValueError, 'in use'):
                    install.install(self.sdk, self.qa, path)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_process_death_at_every_publication_phase(self):
        phases = [('data-page', 0), ('data-page', 1), ('data-flushed', 0), ('before-seal', None),
                  ('seal-written', None), ('committed', None)]
        tools = str(Path(install.__file__).parent)
        for phase, detail in phases:
            with self.subTest(phase=phase, detail=detail):
                self.path.write_bytes(self.original)
                script = (f'import sys,os;sys.path.insert(0,{tools!r});import desktop_install as i;from pathlib import Path;'
                          f'i.install(Path({str(self.sdk)!r}),{str(self.qa)!r},{str(self.path)!r},'
                          f'lambda phase,detail: os._exit(91) if phase=={phase!r} and ({detail!r} is None or detail=={detail!r}) else None)')
                child = subprocess.run([sys.executable, '-c', script], capture_output=True, timeout=10)
                self.assertEqual(child.returncode, 91, child.stderr)
                _, values = self.values()
                self.assertEqual(values[b'apps/index'], b'seed\ncounter\n')
                self.assertEqual(values[b'user/note'], b'preserve\0binary\xff')
                expected = app(version='2') if phase in ('seal-written', 'committed') else app()
                self.assertEqual(values[b'apps/counter.qa'], expected)
                # Reinstall succeeds after death; stale uncommitted tail is safe.
                install.install(self.sdk, self.qa, self.path)
                self.assertEqual(self.values()[1][b'apps/counter.qa'], app(version='2'))

    def test_new_app_and_catalogue_share_one_commit_point(self):
        self.qa.write_bytes(app('new-app'))
        for failure in ('data-page', 'data-flushed', 'before-seal', 'seal-written', 'committed'):
            self.path.write_bytes(self.original)
            def checkpoint(phase, detail):
                if phase == failure:
                    raise RuntimeError('interrupted')
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                install.install(self.sdk, self.qa, self.path, checkpoint)
            _, values = self.values()
            published = failure in ('seal-written', 'committed')
            self.assertEqual(b'apps/new-app.qa' in values, published)
            self.assertEqual(values[b'apps/index'], b'seed\ncounter\nnew-app\n' if published else b'seed\ncounter\n')

    def test_torn_superblock_never_exposes_mixed_update(self):
        real_write = disk.write_exact
        for torn in (0, 1, 17, 40, 64, 95, 1000, disk.PAGE - 1):
            self.path.write_bytes(self.original)
            def write(fd, offset, data):
                if offset in (0, len(self.original) - disk.PAGE):
                    os.pwrite(fd, data[:torn], offset)
                    raise OSError(errno.EIO, 'torn publication')
                real_write(fd, offset, data)
            with patch.object(disk, 'write_exact', write), self.assertRaises(OSError):
                install.install(self.sdk, self.qa, self.path)
            _, values = self.values()
            self.assertIn(values[b'apps/counter.qa'], (app(), app(version='2')))
            self.assertEqual(values[b'apps/index'], b'seed\ncounter\n')
            self.assertEqual(values[b'user/note'], b'preserve\0binary\xff')

    def test_data_and_commit_io_errors_keep_coherent_disk(self):
        real_flush = disk.flush
        for failure in (1, 2):
            self.path.write_bytes(self.original)
            calls = 0
            def flush(fd):
                nonlocal calls
                calls += 1
                if calls == failure:
                    raise OSError(errno.ENOSPC, 'injected sync failure')
                real_flush(fd)
            with patch.object(disk, 'flush', flush), self.assertRaises(OSError):
                install.install(self.sdk, self.qa, self.path)
            _, values = self.values()
            self.assertEqual(values[b'apps/index'], b'seed\ncounter\n')
            self.assertEqual(values[b'apps/counter.qa'], app() if failure == 1 else app(version='2'))

    def test_tombstones_and_long_bulk_keys_preserved(self):
        long_key = b'user/' + b'k' * 5000
        with disk.locked(self.path) as fd:
            current = disk.append(fd, disk.metadata(fd), [(b'user/deleted', b'dead'), (long_key, b'long key value')])
            tombstone = b'QDEL 0 0 user/deleted h7\n'.ljust(disk.PAGE, b'\0')
            disk.write_exact(fd, current.head * disk.PAGE, tombstone)
            disk.flush(fd)
            updated = disk.replace(current, head=current.head + 1, generation=current.generation + 1)
            disk.write_exact(fd, 0 if updated.generation % 2 == 0 else len(self.original) - disk.PAGE, updated.page())
            disk.flush(fd)
        before = self.path.read_bytes()
        install.install(self.sdk, self.qa, self.path)
        _, values = self.values()
        self.assertNotIn(b'user/deleted', values)
        self.assertEqual(values[long_key], b'long key value')
        self.assertEqual(self.path.read_bytes()[disk.PAGE:updated.head * disk.PAGE], before[disk.PAGE:updated.head * disk.PAGE])

    def test_corrupt_committed_record_refused(self):
        raw = bytearray(self.original)
        raw[disk.PAGE * 2 + 20] ^= 1
        self.path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'checksum'):
            install.install(self.sdk, self.qa, self.path)
        self.assertEqual(self.path.read_bytes(), raw)

    def test_catalogue_duplicates_and_missing_archives_refused(self):
        for payload in (b'seed\nseed\n', b'missing\n'):
            self.path.write_bytes(self.original)
            with disk.locked(self.path) as fd:
                disk.append(fd, disk.metadata(fd), [(b'apps/index', payload)])
            before = self.path.read_bytes()
            with self.assertRaises(ValueError):
                install.install(self.sdk, self.qa, self.path)
            self.assertEqual(self.path.read_bytes(), before)


class ArchiveStructure(unittest.TestCase):
    def read(self, raw):
        return archive.read(raw, '22.137', 'aarch64', 'qos.app-session/4', 'qos.desktop/1')

    def test_table_extents_and_trailing_data(self):
        raw = app()
        for damaged in (raw + b'extra', raw[:-1], raw.replace(b'LOAD ', b'MANIFEST ', 1),
                        raw.replace(b'MANIFEST 0 ', b'MANIFEST 1 ', 1)):
            with self.assertRaises(ValueError):
                self.read(damaged)

    def test_module_entry_and_load_bounds(self):
        parts = archive.sections(app())
        for before, after in ((b'entry 0', b'entry 99999'), (b'memsz 512', b'memsz 100'),
                              (b'imagesz 512', b'imagesz 511'), (b'memsz 512', b'memsz ' + b'9' * 50)):
            with self.assertRaises(ValueError):
                self.read(pack(dict(parts, LOAD=parts['LOAD'].replace(before, after))))
        image = bytearray(parts['IMAGE'])
        image[128:135] = b'noEntry'
        load = parts['LOAD'].replace(hashlib.sha256(parts['IMAGE']).hexdigest().encode(), hashlib.sha256(image).hexdigest().encode())
        with self.assertRaisesRegex(ValueError, 'root appMain'):
            self.read(pack(dict(parts, LOAD=load, IMAGE=bytes(image))))

    def test_module_identities_are_opaque_runtime_bytes(self):
        parts = archive.sections(app())
        image = bytearray(parts['IMAGE'])
        image[96] = 255
        load = parts['LOAD'].replace(hashlib.sha256(parts['IMAGE']).hexdigest().encode(), hashlib.sha256(image).hexdigest().encode())
        self.read(pack(dict(parts, LOAD=load, IMAGE=bytes(image))))

    def test_relocations_and_imports_are_checked_after_hashes(self):
        parts = archive.sections(app())
        for reloc, imports in ((struct.pack('<2I', 16, 16), b''), (struct.pack('<I', 510), b''),
                               (parts['RELOC'], b'c 9000 8 fpr_call\n'), (parts['RELOC'], b'd 320 99 fpr_unit\n')):
            old = hashlib.sha256(parts['RELOC']).hexdigest().encode()
            new = hashlib.sha256(reloc + imports).hexdigest().encode()
            with self.assertRaises(ValueError):
                self.read(pack(dict(parts, RELOC=reloc, IMPORT=imports, LOAD=parts['LOAD'].replace(old, new))))


if __name__ == '__main__':
    unittest.main()
