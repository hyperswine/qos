"""The dependency is explicit and validation never creates a source overlay."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('split_configure', Path(__file__).resolve().parents[1] / 'configure.py')
cfg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cfg)

class DependencyConfiguration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'qos'
        self.dep = Path(self.temp.name).resolve() / 'external' / 'compiler'
        self.root.mkdir()
        for name in ('Makefile', 'compiler/Main.hs', 'hal/core/runtime.c', 'core/prelude.fpr'):
            p = self.dep / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('source')
        self.patch = patch.object(cfg, 'ROOT', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_requires_explicit_environment(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'set FPRISC_ROOT'):
                cfg.dependency()

    def test_non_sibling_dependency_without_files_or_links(self):
        with patch.dict(os.environ, {'FPRISC_ROOT': str(self.dep)}):
            dep = cfg.dependency()
            self.assertEqual(dep, self.dep.resolve())
            cfg.configure(dep)
            cfg.configure(dep, check=True)
            self.assertEqual(list(self.root.iterdir()), [])

    def test_invalid_dependency_does_not_write(self):
        (self.dep / 'hal/core/runtime.c').unlink()
        with self.assertRaisesRegex(ValueError, 'missing hal/core/runtime.c'):
            cfg.configure(self.dep)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_install_uses_bundled_toolchain(self):
        (self.root / '.installed').touch()
        with patch.dict(os.environ, {'FPRISC_ROOT': '/irrelevant/development/path'}):
            self.assertEqual(cfg.dependency(), self.root / 'toolchain')

    def test_dev_watches_external_modules_and_templates_use_search_names(self):
        import argparse
        module = self.dep / 'std' / 'external.fpr'
        module.parent.mkdir()
        module.write_text('value = 42.')
        app = self.root / 'example.fpr'
        app.write_text('X = use "std/external". main = X.value.')
        source = Path(__file__).resolve().parents[1] / 'qos.py'
        cli_spec = importlib.util.spec_from_file_location('qos_cli_test', source)
        cli = importlib.util.module_from_spec(cli_spec)
        with patch.dict(os.environ, {'FPRISC_ROOT': str(self.dep)}):
            cli_spec.loader.exec_module(cli)
        self.assertIn(module.resolve(), cli.watch_set(app))
        with patch.object(cli, 'ROOT', self.root), patch.object(cli, 'FPR', self.root / 'fp-risc'), patch.object(Path, 'cwd', return_value=self.root), patch.object(cli, 'say'):
            cli.cmd_new(argparse.Namespace(template='mvu', name='example'))
        created = (self.root / 'fp-risc/apps/example/app.fpr').read_text()
        self.assertIn('use "std/mvu"', created)
        self.assertNotIn('../../std', created)

    def test_release_refuses_dirty_or_mismatched_compiler(self):
        lock = self.root / 'fprisc.lock.json'
        lock.write_text(json.dumps({'revision': 'expected'}))
        with patch.object(cfg, 'LOCK', lock), patch.object(cfg, 'dependency', return_value=self.dep):
            with patch.object(cfg, 'git', return_value=' M compiler/Main.hs'):
                with self.assertRaisesRegex(ValueError, 'uncommitted changes'):
                    cfg.check_release()
            with patch.object(cfg, 'git', side_effect=['', 'different']):
                with self.assertRaisesRegex(ValueError, 'differs'):
                    cfg.check_release()
            with patch.object(cfg, 'git', side_effect=['', 'expected']):
                self.assertEqual(cfg.check_release(), 'expected')

if __name__ == '__main__':
    unittest.main()
