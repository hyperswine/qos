"""tools/sweep.py reads check-all.sh's legs and chooses which a change reaches.

A wrong answer here is silent: a leg that never runs looks like a pass.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import sweep  # noqa: E402

SCRIPT = '''set -euo pipefail
echo "== first ==" && (true) || leg_failed "${LINENO:-?}"
# sweep: with previous
echo "== second: uses the first's output ==" && (
  true
) || leg_failed "${LINENO:-?}"
# sweep: serial
echo "== third ==" && (true) || leg_failed "${LINENO:-?}"
echo "== fourth: a fixed name ==" && (touch /tmp/fixed) || leg_failed "${LINENO:-?}"
# ---- sweep summary
echo "== not a leg =="
'''


class Legs(unittest.TestCase):
    def test_every_leg_once_with_its_tags(self):
        legs = sweep.legs_of(SCRIPT)
        self.assertEqual([name for name, *_ in legs],
                         ['first', "second: uses the first's output", 'third', 'fourth: a fixed name'])
        self.assertEqual([(serial, follows) for _, _, serial, follows in legs],
                         [(False, False), (False, True), (True, False), (True, False)])
        self.assertIn(') || leg_failed', legs[1][1])

    def test_the_real_script_has_each_leg_the_summary_counts(self):
        text = (ROOT / 'check-all.sh').read_text()
        legs = sweep.legs_of(text)
        counted = sum(1 for line in text.splitlines() if line.startswith('echo "== '))
        self.assertEqual(len(legs), counted)
        self.assertEqual(len({name for name, *_ in legs}), len(legs), 'two legs share a name')


class Affected(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.legs = sweep.legs_of((ROOT / 'check-all.sh').read_text())
        cls.services = sweep.service_scripts()
        cls.table = sweep.reach_table(cls.legs, cls.services)

    def reached(self, *paths):
        return sweep.affected(self.legs, set(paths), self.services, self.table)[0]

    def test_documents_reach_nothing(self):
        self.assertEqual(self.reached('docs/2026-01-01-X.md', 'README.md'), set())

    def test_a_program_the_runtime_or_a_lock_reaches_everything(self):
        for path in ('programs/mods/editapp.fpr', 'qos/portable/main.c', 'qos-app.mk', 'fpr.lock', 'check-all.sh'):
            self.assertEqual(len(self.reached(path)), len(self.legs), path)

    def test_a_tool_a_makefile_names_reaches_everything(self):
        self.assertEqual(len(self.reached('tools/mkqa.py')), len(self.legs))

    def test_a_test_no_leg_names_reaches_everything(self):
        self.assertEqual(len(self.reached('tests/no-such-test.fpr')), len(self.legs))

    def test_a_test_reaches_the_legs_that_name_it(self):
        hit = self.reached('tests/kbdread.fpr')
        # the leg that runs it, and this file's own leg, which names it above
        names = [self.legs[i][0] for i in sorted(hit)]
        self.assertTrue(any('tests/kbdread.fpr' in name for name in names), names)
        self.assertLessEqual(len(hit), 2, names)

    def test_a_test_named_only_in_a_check_table_reaches_the_service_legs(self):
        hit = self.reached('tests/appsession.fpr')
        names = {self.legs[i][0] for i in hit}
        self.assertTrue(any('Main Profile' in name for name in names))
        self.assertTrue(any('service_leg' in self.legs[i][1] for i in hit))
        self.assertLess(len(hit), len(self.legs))


if __name__ == '__main__':
    unittest.main()
