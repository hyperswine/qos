"""The fprisc checkout is one path, found in one order, and nothing is
copied or linked into this tree to use it."""
import argparse
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]


def checkout(where):
    for name in ("Makefile", "compiler/Main.hs", "runtime/runtime.c", "core/prelude.fpr"):
        p = where / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("source")
    return where


class FpriscPath(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name).resolve()
        self.root = base / "qos"
        self.root.mkdir()
        self.dep = checkout(base / "elsewhere" / "fprisc")
        with patch.dict(os.environ, {"FPRISC_ROOT": str(self.dep)}):
            spec = importlib.util.spec_from_file_location("qos_cli_under_test", HERE / "qos.py")
            self.cli = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.cli)

    def test_nothing_found_says_how(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(SystemExit, "qos.py fprisc /path/to/fprisc"):
                self.cli.fprisc_root(None, root=self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_order_flag_env_file_sibling(self):
        sibling = checkout(self.root.parent / "fprisc")
        self.assertEqual(self.cli.fprisc_root(None, root=self.root), (sibling, "the sibling checkout ../fprisc"))
        (self.root / "fprisc.path").write_text(str(self.dep) + "\n")
        self.assertEqual(self.cli.fprisc_root(None, root=self.root), (self.dep, "fprisc.path"))
        env = checkout(self.root.parent / "from-env")
        with patch.dict(os.environ, {"FPRISC_ROOT": str(env)}):
            self.assertEqual(self.cli.fprisc_root(None, root=self.root), (env, "$FPRISC_ROOT"))
            flag = checkout(self.root.parent / "from-flag")
            self.assertEqual(self.cli.fprisc_root(str(flag), root=self.root), (flag, "--fprisc"))

    def test_a_named_path_must_be_a_checkout(self):
        (self.dep / "compiler/Main.hs").unlink()
        with patch.dict(os.environ, {"FPRISC_ROOT": str(self.dep)}):
            with self.assertRaisesRegex(SystemExit, "not an fprisc checkout"):
                self.cli.fprisc_root(None, root=self.root)

    def test_installed_tree_uses_its_toolchain(self):
        (self.root / ".installed").touch()
        with patch.dict(os.environ, {"FPRISC_ROOT": "/irrelevant"}):
            self.assertEqual(self.cli.fprisc_root(None, root=self.root), (self.root / "toolchain", "the installed toolchain"))

    def test_fprisc_command_remembers_the_path(self):
        with patch.object(self.cli, "FPRISC_FILE", self.root / "fprisc.path"), patch.object(self.cli, "say"):
            self.cli.cmd_fprisc(argparse.Namespace(path=str(self.dep), pin=False, print=False))
        self.assertEqual((self.root / "fprisc.path").read_text().strip(), str(self.dep))
        def refuse(msg, code=1):
            raise SystemExit(msg)
        with patch.object(self.cli, "FPRISC_FILE", self.root / "fprisc.path"), patch.object(self.cli, "die", refuse):
            with self.assertRaisesRegex(SystemExit, "not an fprisc checkout"):
                self.cli.cmd_fprisc(argparse.Namespace(path=str(self.root), pin=False, print=False))

    def test_dev_watches_external_modules_and_new_apps_land_in_apps(self):
        module = self.dep / "std" / "external.fpr"
        module.parent.mkdir()
        module.write_text("value = 42.")
        app = self.root / "example.fpr"
        app.write_text('X = use "std/external". main = X.value.')
        self.assertIn(module.resolve(), self.cli.watch_set(app))
        with patch.object(self.cli, "ROOT", self.root), patch.object(Path, "cwd", return_value=self.root), patch.object(self.cli, "say"):
            self.cli.cmd_new(argparse.Namespace(template="mvu", name="example"))
        created = (self.root / "apps/example/app.fpr").read_text()
        self.assertIn('use "std/mvu"', created)
        self.assertNotIn("../../std", created)


if __name__ == "__main__":
    unittest.main()
