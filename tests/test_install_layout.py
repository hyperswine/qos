"""`qos.py install` lays down the app SDK by default; --full keeps the
contributor tree.  The SDK list must stay a subset of the full one and
must keep what an app build reads (qos-app.mk, appside, the runtime)."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]


class InstallLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        dep = Path(cls.temp.name) / "fprisc"
        for name in ("Makefile", "compiler/Main.hs", "runtime/runtime.c", "core/prelude.fpr"):
            (dep / name).parent.mkdir(parents=True, exist_ok=True)
            (dep / name).write_text("source")
        with patch.dict(os.environ, {"FPRISC_ROOT": str(dep)}):
            spec = importlib.util.spec_from_file_location("qos_install_under_test", HERE / "qos.py")
            cls.cli = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.cli)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_sdk_is_a_subset_of_full(self):
        full = set(self.cli.INSTALL_TREE_FULL)
        for item in self.cli.INSTALL_TREE_SDK:
            self.assertTrue(item in full or any(item.startswith(f + "/") for f in full), item)
        self.assertLessEqual(set(self.cli.TOOLCHAIN_SDK), set(self.cli.TOOLCHAIN_FULL))

    def test_sdk_keeps_what_an_app_build_reads(self):
        for item in ("qos.py", "dependency.mk", "Makefile", "qos-app.mk", "std", "core", "hal", "loader",
                     "tools", "programs/mods", ".fpr", "fpr.lock", "qos/appside", "qos/portable", "qos/qosp"):
            self.assertIn(item, self.cli.INSTALL_TREE_SDK)
        for item in ("fpr", "core", "std", "runtime", "machine"):
            self.assertIn(item, self.cli.TOOLCHAIN_SDK)

    def test_sdk_drops_sources_tests_docs(self):
        for item in ("tests", "docs", "models", "apps", "qos/native", "qos/tests-host"):
            self.assertNotIn(item, self.cli.INSTALL_TREE_SDK)
        for item in ("compiler", "tests", "docs"):
            self.assertNotIn(item, self.cli.TOOLCHAIN_SDK)

    def test_every_listed_path_exists_in_the_tree(self):
        for item in self.cli.INSTALL_TREE_SDK:
            if item in ("qos/qosp", "qos/qosp-gl", ".fpr", "fpr.lock"):
                continue  # built or generated
            self.assertTrue((HERE / item).exists(), item)


if __name__ == "__main__":
    unittest.main()
