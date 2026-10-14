import importlib.util
import os
from pathlib import Path
import signal
import sys
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('profile', ROOT/'tools/gui-profile-report.py')
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)

sys.path.insert(0, str(ROOT/'tools/pi4'))
spec_memory = importlib.util.spec_from_file_location('main_soak', ROOT/'tools/pi4/main-soak.py')
main_soak = importlib.util.module_from_spec(spec_memory)
spec_memory.loader.exec_module(main_soak)

class MemoryBounds(unittest.TestCase):
    def samples(self, roots, reserved=47000):
        return [{'allocator': {'arc_roots': r, 'reserved_kib': reserved}} for r in roots]
    def test_warmup_and_steady_bounds(self):
        result = main_soak.memory_summary(self.samples([200,100,50,14,15,14]))
        self.assertTrue(result['verified'])
        self.assertEqual(result['roots_max'],15)
        self.assertFalse(main_soak.memory_summary(self.samples([14]*4))['verified'])
    def test_rss_alone_cannot_hide_retained_roots(self):
        with self.assertRaises(RuntimeError):
            main_soak.memory_summary(self.samples([14,14,14,14,23]))
        samples = self.samples([14]*5)
        samples[-1]['allocator']['reserved_kib'] += 4097
        with self.assertRaises(RuntimeError): main_soak.memory_summary(samples)

LOG = '''[gfx-profile] input us=100 kind=4 a=106 b=1
gui-profile: update seq=1 key=106 begin_us=110 end_us=120
gui-profile: view seq=0 key=0 input_us=0 begin_us=101 end_us=109
[gfx-profile] frame start_us=130 drawn_us=140 submitted_us=150 end_us=151 retained=0 finish=0
gui-profile: view seq=1 key=106 input_us=110 begin_us=160 end_us=170
[gfx-profile] frame start_us=180 drawn_us=190 submitted_us=200 end_us=230 retained=0 finish=1
'''

class Correlation(unittest.TestCase):
    def test_older_inflight_frame_does_not_satisfy_input(self):
        result = profile.report(LOG)
        self.assertEqual(result['samples'][0]['poll_to_submission_us'], 100)
        self.assertEqual(result['samples'][0]['poll_to_completion_us'], 130)
    def test_native_mirror_and_startup_do_not_double_count(self):
        startup = '[gfx-profile] frame start_us=1 drawn_us=2 submitted_us=3 end_us=4 retained=0 finish=0\n'
        lines = []
        for line in LOG.splitlines():
            lines.append(line)
            if line.startswith('[gfx-profile]'): lines.append('[host] '+line)
        result = profile.report(startup+'\n'.join(lines))
        self.assertEqual(result['frames'], 2)
        self.assertEqual(result['unmeasured_startup_frames'], 1)
        self.assertEqual(result['inputs_with_frame'], 1)
    def test_identity_and_order_are_required(self):
        for text in (LOG.replace('input_us=110', 'input_us=111'),
                     LOG.replace('submitted_us=200', 'submitted_us=189'),
                     LOG.rsplit('[gfx-profile] frame', 1)[0]):
            with self.assertRaises(ValueError): profile.report(text)
    def test_retained_pixels_do_not_claim_a_submission(self):
        result = profile.report(LOG.replace('retained=0 finish=1', 'retained=1 finish=1'))
        self.assertEqual(result['retained_frames'], 1)
        self.assertEqual(result['metrics']['poll_to_submission_us']['count'], 0)
    def test_coalesced_and_quit_updates_are_reported(self):
        extra = '[gfx-profile] input us=240 kind=4 a=16 b=1\ngui-profile: update seq=2 key=16 begin_us=250 end_us=260\n'
        self.assertEqual(profile.report(LOG+extra)['updates_without_frame'], [2])

class PolicyGuard(unittest.TestCase):
    def test_restore_success_failure_and_interrupted_wait(self):
        for mode in ('success', 'failure', 'signal', 'hangup'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                policy = root/'sys/policy0'; policy.mkdir(parents=True)
                for name,value in {'scaling_governor':'powersave', 'scaling_available_governors':'powersave performance',
                                   'scaling_min_freq':'600000', 'scaling_max_freq':'1500000'}.items():
                    (policy/name).write_text(value+'\n')
                env = dict(os.environ, QOSP_CPU_POLICY_ROOT=str(root/'sys'), QOSP_CPU_POLICY_LOCK=str(root/'lock'))
                command = 'sleep .2; exit '+('7' if mode=='failure' else '0')
                p = subprocess.Popen(['sh',str(ROOT/'tools/pi4/cpu-policy-run.sh'),'performance','sh','-c',command],
                                     env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                end = time.monotonic()+2
                while (policy/'scaling_governor').read_text().strip() != 'performance':
                    self.assertLess(time.monotonic(), end); time.sleep(.005)
                if mode in ('signal','hangup'):
                    p.send_signal(signal.SIGTERM if mode=='signal' else signal.SIGHUP)
                p.communicate(timeout=5)
                self.assertEqual(p.returncode, {'failure':7, 'signal':143}.get(mode,0))
                self.assertEqual((policy/'scaling_governor').read_text().strip(),'powersave')
                self.assertFalse((root/'lock').exists())

if __name__ == '__main__': unittest.main()
