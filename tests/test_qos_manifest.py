"""qos.toml: `qos new` writes it, `qos run` / `qos pack` read it, and a
project without one keeps the old behaviour (docs/2026-10-28-PORTABLE-APP-WORKFLOW.md)."""
import argparse
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]


def fake_fprisc(where):
    for name in ("Makefile", "compiler/Main.hs", "runtime/runtime.c", "core/prelude.fpr"):
        p = where / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("source")
    return where


class Manifest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        dep = fake_fprisc(self.base / "fprisc")
        with patch.dict(os.environ, {"FPRISC_ROOT": str(dep)}):
            spec = importlib.util.spec_from_file_location("qos_manifest_under_test", HERE / "qos.py")
            self.cli = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.cli)
        self.cwd = os.getcwd()
        self.proj = self.base / "work"
        self.proj.mkdir()
        os.chdir(self.proj)
        self.addCleanup(os.chdir, self.cwd)

    def write(self, text, entry="app.fpr"):
        d = self.proj / "p"
        d.mkdir(exist_ok=True)
        (d / entry).write_text("main = 0.\n")
        (d / "qos.toml").write_text(text)
        return d

    def test_new_writes_manifest_assets_gitignore(self):
        self.cli.cmd_new(argparse.Namespace(name="hello", template="min"))
        d = self.proj / "hello"
        self.assertTrue((d / "app.fpr").is_file())
        self.assertTrue((d / "assets").is_dir())
        self.assertIn(".qos/", (d / ".gitignore").read_text())
        t = self.cli.parse_toml((d / "qos.toml").read_text())
        self.assertEqual(t["app"], {"id": "hello", "name": "hello", "version": "0.1.0"})
        self.assertEqual(t["build"], {"entry": "app.fpr", "target": "qos-portable"})
        m = self.cli.load_manifest(d / "qos.toml")
        self.assertEqual((m["id"], m["entry"], m["assets"]), ("hello", d / "app.fpr", d / "assets"))

    def test_subset_parser_matches_tomllib(self):
        text = self.cli.NEW_MANIFEST.format(name="x") + 'extra = 3  # c\nflag = true\n'
        self.assertEqual(self.cli._toml_subset(text), self.cli.parse_toml(text))

    def test_find_project_dir_and_entry_file(self):
        d = self.write('[app]\nid = "my-app"\nname = "My App"\nversion = "1.2.3"\n[build]\nentry = "app.fpr"\n')
        m, prog = self.cli.find_project(str(d))
        self.assertEqual((m["id"], m["name"], m["version"]), ("my-app", "My App", "1.2.3"))
        self.assertEqual(prog, str(d / "app.fpr"))
        m2, prog2 = self.cli.find_project("p/app.fpr")
        self.assertEqual((m2["id"], prog2), ("my-app", "p/app.fpr"))
        self.assertEqual(self.cli.manifest_make_vars(m),
                         ["QA_ID=my-app", "QA_NAME=My App", "QA_VERSION=1.2.3"])
        self.assertIsNone(m["assets"])

    def test_no_manifest_falls_back(self):
        (self.proj / "old.fpr").write_text("main = 0.\n")
        self.assertEqual(self.cli.find_project("old.fpr"), (None, "old.fpr"))
        self.assertEqual(self.cli.manifest_make_vars(None), [])

    def test_other_file_beside_manifest_is_not_the_app(self):
        d = self.write('[app]\nid = "a"\n[build]\nentry = "app.fpr"\n')
        (d / "helper.fpr").write_text("x = 1.\n")
        self.assertEqual(self.cli.find_project("p/helper.fpr"), (None, "p/helper.fpr"))

    def test_bad_manifests_are_refused_by_name(self):
        cases = [
            ('[app]\nid = "../x"\n[build]\nentry = "app.fpr"\n', "may use only|may not start"),
            ('[app]\nid = ".x"\n[build]\nentry = "app.fpr"\n', "may not start"),
            ('[app]\nid = "a..b"\n[build]\nentry = "app.fpr"\n', "may not contain"),
            ('[app]\nid = "' + "a" * 65 + '"\n[build]\nentry = "app.fpr"\n', "longer than 64"),
            ('[app]\nname = "n"\n[build]\nentry = "app.fpr"\n', "missing"),
            ('[app]\nid = "a"\n[build]\n', "entry is required"),
            ('[app]\nid = "a"\n[build]\nentry = "nope.fpr"\n', "no such file"),
            ('[app]\nid = "a"\n[build]\nentry = "app.fpr"\ntarget = "native"\n', "only \"qos-portable\""),
            ('[app]\nid = "a"\nname = "x\\"y"\n[build]\nentry = "app.fpr"\n', "without quotes"),
        ]
        def die(msg, code=1):
            raise SystemExit(msg)
        for text, err in cases:
            d = self.write(text)
            with self.subTest(text=text), patch.object(self.cli, "die", die):
                with self.assertRaisesRegex(SystemExit, err):
                    self.cli.load_manifest(d / "qos.toml")

    def test_directory_without_manifest_dies(self):
        (self.proj / "empty").mkdir()
        with patch("sys.stderr"), self.assertRaises(SystemExit):
            self.cli.find_project("empty")


if __name__ == "__main__":
    unittest.main()
