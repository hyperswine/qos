#!/usr/bin/env python3
"""Check an offline Main archive upgrade preserves user history and fails closed."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('update_main_disk', Path(__file__).with_name('update-main-disk.py'))
up = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = up
spec.loader.exec_module(up)


def record(tag, key, payload):
    n = (len(payload) + up.PG - 1) // up.PG
    line = f'{tag} {n} {len(payload)} {key} h{up.digest(payload)}\n'.encode()
    return line.ljust(up.PG, b'\0') + payload.ljust(n * up.PG, b'\0')


def fixture():
    body = record('QREC', 'apps/index', b'clock\nlogs\nbrowser\ndisk\n')
    body += record('QREC', 'user/note', b'keep this\0binary\xff')
    body += record('QREC', 'deleted', b'old') + record('QDEL', 'deleted', b'')
    body += record('QBLK', '2', b'3 user/chunk\none4 user/other\ntwo!')
    data = bytearray(64 * up.PG)
    data[up.PG:up.PG + len(body)] = body
    meta = up.Meta(1 + len(body) // up.PG, 0, 1, 56, 56, 0, 8, 0)
    data[:up.PG] = meta.line().ljust(up.PG, b'\0')
    data[-up.PG:] = up.replace(meta, generation=9).line().ljust(up.PG, b'\0')
    return data, meta


class Upgrade(unittest.TestCase):
    def setUp(self):
        self.data, self.meta = fixture()
        self.archives = {a: (a + '-new').encode() for a in up.APPS}

    def test_preserves_history_and_user_values_and_both_fallbacks(self):
        original = bytes(self.data)
        result, report = up.prepare(self.data, self.archives)
        self.assertEqual(bytes(self.data), original)
        self.assertEqual(result[up.PG:self.meta.head * up.PG], original[up.PG:self.meta.head * up.PG])
        old, _ = up.scan(original, self.meta.head)
        for page in (result[:up.PG], result[-up.PG:]):
            meta = up.parse_seal(page, len(result) // up.PG)
            new, _ = up.scan(result, meta.head)
            for key, value in old.items():
                self.assertEqual(new[key], value)
            self.assertNotIn(b'deleted', new)
            for a, payload in self.archives.items():
                self.assertEqual(new[f'apps/{a}.qa'.encode()], payload)
        self.assertEqual(report['preserved_records'], 5)
        self.assertEqual(report['new_generation'], 11)

    def refuses(self, data, message):
        original = bytes(data)
        with self.assertRaisesRegex(ValueError, message):
            up.prepare(data, self.archives)
        self.assertEqual(bytes(data), original)

    def test_corrupt_superblock(self):
        self.data[10] ^= 1
        self.refuses(self.data, 'superblock')

    def test_pending_operation(self):
        self.data[-up.PG:] = up.replace(self.meta, generation=9, w=2, c=0, stage=99).line().ljust(up.PG, b'\0')
        self.refuses(self.data, 'pending')

    def test_payload_corruption(self):
        self.data[2 * up.PG] ^= 1
        self.refuses(self.data, 'checksum')

    def test_torn_record(self):
        self.data[up.PG:2 * up.PG] = b'QREC 900 24 apps/index h0\n'.ljust(up.PG, b'\0')
        self.refuses(self.data, 'bounds/shape')

    def test_bulk_framing(self):
        # Keep hash bypass valid while corrupting its inner frame length.
        p = self.data.find(b'QBLK ')
        self.data[p:p + up.PG] = b'QBLK 1 33 2 h0\n'.ljust(up.PG, b'\0')
        self.data[p + up.PG:p + up.PG + 2] = b'99'
        self.refuses(self.data, 'bulk')

    def test_conflicting_generations(self):
        self.data[-up.PG:] = up.replace(self.meta, head=self.meta.head - 1).line().ljust(up.PG, b'\0')
        self.refuses(self.data, 'conflicting')

    def test_capacity(self):
        self.archives['clock'] = b'x' * (56 * up.PG)
        self.refuses(self.data, 'insufficient')

    def test_custom_index(self):
        # Valid checksum and bounds, but a fifth app needs its own ABI upgrade.
        payload = b'clock\nlogs\nbrowser\ndisk\ncustom\n'
        self.data[up.PG:3 * up.PG] = record('QREC', 'apps/index', payload)
        self.refuses(self.data, 'custom/missing')

    def test_cli_preserves_source_and_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source, output = base / 'source.disk', base / 'output.disk'
            source.write_bytes(self.data)
            for app, payload in self.archives.items():
                (base / (app + '.qa')).write_bytes(payload)
            cmd = [sys.executable, str(Path(up.__file__)), str(source), str(output), str(base)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            expected = output.read_bytes()
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_bytes(), expected)
            self.assertEqual(source.read_bytes(), self.data)
            output.unlink()
            source.write_bytes(b'corrupt')
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
