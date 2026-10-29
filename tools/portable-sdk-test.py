#!/usr/bin/env python3
"""Fast project-contract checks; no compiler/toolchain processes required."""
from pathlib import Path
import tempfile
import json
from unittest.mock import patch
import unittest
import portable_sdk as sdk


class ProjectContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "counter-example"
        sdk.scaffold(self.root)
        self.manifest = self.root / "qos.toml"
        self.original = self.manifest.read_text()

    def test_identity_survives_directory_and_entry_rename(self):
        (self.root / "main.fpr").rename(self.root / "different.fpr")
        self.manifest.write_text(self.original.replace('"main.fpr"', '"different.fpr"'))
        moved = self.root.rename(self.root.with_name("renamed"))
        root, app, entry = sdk.project(moved / "assets")
        self.assertEqual(app["id"], "counter-example")
        self.assertEqual(entry, (moved / "different.fpr").resolve())

    def test_archive_id_rules(self):
        for value in ("a", "_", "A.b-0_", "x" * 64):
            self.assertTrue(sdk.valid_id(value), value)
        for value in ("", ".a", "-a", "a..b", "a/b", "a b", "é", "x" * 65):
            self.assertFalse(sdk.valid_id(value), value)

    def test_bad_schema_target_and_entry_refused(self):
        for old, new in [('"desktop"', '"process"'), ('"qos-portable"', '"posix"'),
                         ('"main.fpr"', '"../escape.fpr"'), ('"main.fpr"', '"missing.fpr"'),
                         ('version = "0.1.0"', 'version = 1'), ('[app]', '[typo]'),
                         ('kind = "desktop"', 'kind = "desktop"\nunknown = true')]:
            with self.subTest(new=new):
                self.manifest.write_text(self.original.replace(old, new))
                with self.assertRaises(ValueError):
                    sdk.project(self.root)

    def test_assets_not_silently_dropped(self):
        (self.root / "assets/icon.png").write_bytes(b"an asset")
        with self.assertRaisesRegex(ValueError, "asset packaging"):
            sdk.project(self.root)

    def test_entry_symlink_escape_refused(self):
        (self.root / "main.fpr").unlink()
        outside = self.root.parent / "outside.fpr"
        outside.write_text("main = Unit.\n")
        (self.root / "main.fpr").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "inside the project"):
            sdk.project(self.root)

    def test_incompatible_sdk_and_mixed_compiler_refused(self):
        fake = self.root.parent / "sdk"
        (fake / "compiler").mkdir(parents=True)
        (fake / "compiler/fpr").write_bytes(b"fake compiler")
        metadata = dict(format=1, desktopApi=sdk.API, desktopSession=sdk.SESSION,
                        os=sdk.sys.platform, architecture=sdk.native()[0], compilerSha256="wrong")
        with patch.object(sdk, "ROOT", fake):
            for field, value in (("architecture", "wrong"), ("desktopSession", "old"), ("desktopApi", "old")):
                (fake / "sdk.json").write_text(json.dumps(dict(metadata, **{field: value})))
                with self.assertRaisesRegex(ValueError, "incompatible SDK"):
                    sdk.build(self.root)
            (fake / "sdk.json").write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError, "selected fpr and SDK differ"):
                sdk.build(self.root, compiler="/different/fpr")
            with self.assertRaisesRegex(ValueError, "compiler changed"):
                sdk.build(self.root)

    def test_existing_destination_preserved(self):
        with self.assertRaisesRegex(ValueError, "already exists"):
            sdk.scaffold(self.root)
        self.assertEqual(self.manifest.read_text(), self.original)


if __name__ == "__main__":
    unittest.main()
