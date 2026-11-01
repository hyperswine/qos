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


APP_V2 = """manifest = 2

[app]
id = "game"
name = "Game"
version = "1.0.0"
kind = "app"

[build]
entry = "main.fpr"
target = "qos-portable"
optimize = "checks-only"
compiler-memory-mb = 2048

[run]
display = "gl"
disk-mb = 32

[sdk]
version = "0.3.0"
"""


class ManifestV2(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "game"
        self.root.mkdir()
        (self.root / "main.fpr").write_text("main = Unit.\n")
        self.manifest = self.root / "qos.toml"
        self.manifest.write_text(APP_V2)

    def test_app_project(self):
        found = sdk.load(self.root)
        self.assertEqual((found["manifest"], found["app"]["kind"], found["run"]["display"], found["sdk"]["version"]),
                         (2, "app", "gl", "0.3.0"))
        self.assertEqual(sdk.project(self.root)[1]["id"], "game")

    def test_minimal_app_and_v2_desktop(self):
        self.manifest.write_text(APP_V2.split("optimize")[0])
        self.assertEqual(sdk.load(self.root)["run"], {})
        self.manifest.write_text(APP_V2.split("optimize")[0].replace('"app"', '"desktop"'))
        self.assertEqual(sdk.load(self.root)["app"]["kind"], "desktop")

    def test_refusals(self):
        for old, new in [("manifest = 2", "manifest = 3"), ("manifest = 2", "manifest = true"),
                         ('kind = "app"', 'kind = "service"'), ('"checks-only"', '"fast"'),
                         ("2048", "true"), ("2048", "0"), ('"gl"', '"vulkan"'), ('"gl"', '["gl"]'), ('"checks-only"', '["full"]'), ("disk-mb = 32", "disk-mb = 0"),
                         ("disk-mb = 32", "disk-mb = 32\nport = 70000"), ("disk-mb = 32", "disk-mb = 32\nhost = 1"),
                         ('version = "0.3.0"\n', 'version = "0.3"\n'), ('version = "0.3.0"\n', 'version = ">=0.3.0"\n'),
                         ("[sdk]", "[platform]"), ('[run]\ndisplay = "gl"\ndisk-mb = 32\n', ""),
                         ("[sdk]", "[sdk]\nchannel = 1")]:
            if new == "":
                # [run] belongs to kind = "app"; a desktop manifest with one is refused
                text = APP_V2.replace('kind = "app"', 'kind = "desktop"')
            else:
                text = APP_V2.replace(old, new, 1)
            with self.subTest(new=new):
                self.manifest.write_text(text)
                with self.assertRaises(ValueError):
                    sdk.load(self.root)

    def test_sdk_pin(self):
        pin = {"version": "0.3.0"}
        for release in ("0.3.0", "0.3.1", "0.4.0"):
            sdk.check_sdk_version(pin, {"release": release})
        for release in ("0.2.0", "1.0.0"):
            with self.assertRaises(ValueError):
                sdk.check_sdk_version(pin, {"release": release})
        sdk.check_sdk_version({"version": "=0.3.0"}, {"release": "0.3.0"})
        with self.assertRaisesRegex(ValueError, "pins SDK =0.3.0"):
            sdk.check_sdk_version({"version": "=0.3.0"}, {"release": "0.3.1"})
        sdk.check_sdk_version(pin, {})  # a development stage says so and builds

    def test_compiler_settings(self):
        env = {"GHCRTS": "-M1M", "PATH": "/bin"}
        sdk.compiler_settings(env, {"optimize": "checks-only", "compiler-memory-mb": 2048})
        self.assertEqual(env["GHCRTS"], "-M2048M -A32M")
        self.assertEqual(sorted(k for k in env if k.startswith("FPR_NO_")),
                         sorted("FPR_NO_" + n for n in sdk.OPTIMIZE["checks-only"]))
        env = {"GHCRTS": "-M1M"}
        sdk.compiler_settings(env, {})
        self.assertEqual(env, {})

    def test_platform_inventory_checked(self):
        fake = Path(self.temp.name) / "sdk"
        files = {}
        for name in (*sdk.PLATFORM_UNITS, sdk.PLATFORM_LINKER_SCRIPT):
            (fake / "platform" / name).parent.mkdir(parents=True, exist_ok=True)
            (fake / "platform" / name).write_text(name)
            files[name] = sdk.digest(fake / "platform" / name)
        meta = dict(platformFiles=files, platformSha256=sdk.platform_digest(files))
        sdk.platform_inputs(fake, meta)
        (fake / "platform/appside/hal.c").write_text("changed")
        with self.assertRaisesRegex(ValueError, "appside/hal.c changed"):
            sdk.platform_inputs(fake, meta)
        with self.assertRaisesRegex(ValueError, "no kind"):
            sdk.platform_inputs(fake, dict(meta, platformSha256="other"))


if __name__ == "__main__":
    unittest.main()
