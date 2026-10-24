"""Real-process isolation, bounded scheduling, cleanup and coverage contracts."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from service_checks import CHECKS, Check
spec = importlib.util.spec_from_file_location('service_runner', ROOT / 'tools/check-services.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def alive(pid):
    try:
        os.kill(pid, 0)
        # A killed orphan can remain a zombie briefly while PID 1 reaps it.
        if Path('/proc').is_dir():
            state = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
        else:
            state = subprocess.check_output(['ps', '-o', 'stat=', '-p', str(pid)], text=True).strip()
        return bool(state) and not state.startswith('Z')
    except (ProcessLookupError, FileNotFoundError, subprocess.CalledProcessError):
        return False


class Services(unittest.TestCase):
    def fixture(self, directory, names):
        root = Path(directory).resolve()
        tree = root / 'snapshot'
        (tree / 'tools').mkdir(parents=True)
        shutil.copy2(ROOT / 'tools/service_worker.py', tree / 'tools/service_worker.py')
        for name, code in names.items():
            (tree / 'tools' / (name + '-check.py')).write_text(code)
        return runner.Runner(root, ROOT.parent / 'fprisc', 2)

    def test_registered_coverage_and_workflow(self):
        self.assertEqual(len(CHECKS), 16)
        self.assertEqual(len({c.name for c in CHECKS}), 16)
        self.assertEqual([c.name for c in CHECKS if c.exclusive], ['portable-shutdown'])
        for c in CHECKS:
            self.assertTrue((ROOT / c.script).is_file(), c.script)
        workflow = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertIn('tools/check-services.py --jobs 2', workflow)
        sweep = (ROOT / 'check-all.sh').read_text()
        self.assertLess(sweep.index('== QOSPortable host+run'), sweep.index('== clause groups:'))
        for c in CHECKS:
            self.assertEqual(sweep.count('service_leg ' + c.name + ')'), 1)

    def test_snapshot_uses_working_files_without_aliases_or_ignored_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source';source.mkdir()
            subprocess.run(['git', 'init', '-q', source], check=True)
            (source / '.gitignore').write_text('build/\n')
            (source / 'input').write_text('current local edit')
            (source / 'build').mkdir();(source / 'build/stale').write_text('stale')
            dest = Path(tmp) / 'snapshot'
            info = runner.snapshot(source, dest)
            self.assertEqual(info['files'], 2)
            self.assertFalse((dest / 'build').exists())
            self.assertFalse((dest / '.git').exists())
            (dest / 'input').write_text('private mutation')
            self.assertEqual((source / 'input').read_text(), 'current local edit')

    def test_parallel_checks_get_private_fixed_paths_cache_temp_port_and_logs(self):
        code = '''import os,pathlib,tempfile,time,subprocess,sys,socket
subprocess.run([sys.executable,'-c','import signal; assert signal.SIGTERM not in signal.pthread_sigmask(signal.SIG_BLOCK, []); print("child command complete")'],check=True)
root=pathlib.Path.cwd()
(root/'build').mkdir();(root/'build/prog.s').write_text(__file__)
(root/'app.qa').write_text(__file__)
(root/'qosp.disk').write_text(__file__)
assert os.environ['FPR_PORT']=='0'
sock=socket.socket();sock.bind(('127.0.0.1',int(os.environ['FPR_PORT'])));sock.listen()
(root.parent/'port').write_text(str(sock.getsockname()[1]))
deadline=time.monotonic()+5
while len(list(root.parents[1].glob('*/port')))<2:
 assert time.monotonic()<deadline
 time.sleep(.01)
assert 'BUILD' not in os.environ and 'QA_OUT' not in os.environ and 'MAKEFLAGS' not in os.environ
assert 'FPRD_SOCK' not in os.environ and 'QOSP_READY_FILE' not in os.environ
assert 'FPR_EVDEV' not in os.environ and 'QOS_STORE_TEST_FAIL_SYNC_AT' not in os.environ
assert str(root.parent) in os.environ['FPR_DISK']
pathlib.Path(os.environ['FPR_DISK']).write_text('private block state')
assert os.environ['FPR_HOME']==str(root)
assert str(root.parent) in tempfile.gettempdir()
pathlib.Path(os.environ['XDG_CACHE_HOME']).mkdir()
time.sleep(.15)
assert (root/'app.qa').read_text()==__file__
print('private HOLDS')
'''
        with tempfile.TemporaryDirectory() as tmp:
            r = self.fixture(tmp, {'one': code, 'two': code})
            ambient = {'FPR_DISK': str(Path(tmp)/'external.disk'), 'FPRD_SOCK':'external.sock',
                       'QOSP_READY_FILE':'external.ready','FPR_EVDEV':'external-device',
                       'QOS_STORE_TEST_FAIL_SYNC_AT':'1', 'BUILD':'/external/build',
                       'QA_OUT':'/external/archive.qa','MAKEFLAGS':'-j99'}
            with patch.dict(os.environ,ambient):
                self.assertTrue(r.run([Check('one'), Check('two')]))
            self.assertFalse((Path(tmp)/'external.disk').exists())
            for name in ('one', 'two'):
                job = Path(tmp) / 'jobs' / name
                self.assertIn('private HOLDS', (job / 'output.log').read_text())
                self.assertTrue((job / 'tree/build/prog.s').is_file())
            self.assertFalse((Path(tmp) / 'snapshot/app.qa').exists())
            self.assertNotEqual((Path(tmp)/'jobs/one/port').read_text(),
                                (Path(tmp)/'jobs/two/port').read_text())

    def test_exclusive_and_worker_bound_without_timing_thresholds(self):
        import threading
        active=[]; peak=[];exclusive=[];lock=threading.Lock()
        with tempfile.TemporaryDirectory() as tmp:
            r=runner.Runner(Path(tmp), ROOT, 2)
            def one(check):
                with lock:
                    if check.exclusive:exclusive.append(len(active))
                    active.append(check.name);peak.append(len(active))
                time.sleep(.03)
                with lock:active.remove(check.name)
                return {'status':'ok','seconds':0}
            with patch.object(r,'one',side_effect=one):
                self.assertTrue(r.run([Check('a'),Check('exclusive',exclusive=True),Check('b'),Check('c')]))
            self.assertEqual(exclusive,[0])
            self.assertLessEqual(max(peak),2)
            self.assertEqual(max(peak),2)

    def test_partial_failure_keeps_each_verdict_and_other_checks_finish(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=runner.Runner(Path(tmp), ROOT, 2)
            def one(check):
                return {'status':'failed' if check.name=='files-service' else 'ok','seconds':0}
            with patch.object(r,'one',side_effect=one):
                self.assertFalse(r.run([Check('files-service'),Check('editor-policy')]))
            for name,code in (('files-service',1),('editor-policy',0),('preferences',1)):
                result=subprocess.run([sys.executable,ROOT/'tools/check-services.py',
                                       '--verdict',name,'--results',Path(tmp)/'results.json'],
                                      capture_output=True,text=True)
                self.assertEqual(result.returncode,code,result.stdout+result.stderr)

    def test_shell_subgroups_and_forced_worker_kill_are_cleaned(self):
        if not shutil.which('timeout'):
            self.skipTest('needs timeout')
        with tempfile.TemporaryDirectory() as tmp:
            code='''import subprocess,sys,time,pathlib,signal
signal.signal(signal.SIGTERM,signal.SIG_IGN)
child="import os,pathlib,time;pathlib.Path('../child.pid').write_text(str(os.getpid()));time.sleep(120)"
p=subprocess.Popen(['sh','-c','timeout 120 "$@"; true','sh',sys.executable,'-c',child])
time.sleep(120)
'''
            r=self.fixture(tmp,{'probe':code})
            result=r.one(Check('probe',timeout=1))
            self.assertEqual(result['status'],'timeout')
            pid=int((Path(tmp)/'jobs/probe/child.pid').read_text())
            deadline=time.monotonic()+3
            while alive(pid) and time.monotonic()<deadline:time.sleep(.02)
            self.assertFalse(alive(pid),f'shell subgroup child {pid} survived forced worker kill')

    def test_cancellation_stops_active_workers_and_their_children(self):
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            code='''import subprocess,sys,pathlib,time
p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'])
pathlib.Path('../child.pid').write_text(str(p.pid))
time.sleep(120)
'''
            r=self.fixture(tmp,{'probe':code});results=[]
            thread=threading.Thread(target=lambda:results.append(r.one(Check('probe'))))
            thread.start()
            marker=Path(tmp)/'jobs/probe/child.pid'
            deadline=time.monotonic()+5
            while not marker.exists() and time.monotonic()<deadline:time.sleep(.02)
            self.assertTrue(marker.exists(),'worker never reached readiness')
            pid=int(marker.read_text());r.cancel();thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
            self.assertEqual(results[0]['status'],'cancelled')
            self.assertFalse(alive(pid))

    def test_failure_and_timeout_kill_children_in_independent_sessions(self):
        for mode in ('failed','timeout'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                code='''import subprocess,sys,time,pathlib
p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'],start_new_session=True)
pathlib.Path('../child.pid').write_text(str(p.pid))
'''+('raise RuntimeError("injected failure")\n' if mode=='failed' else 'time.sleep(120)\n')
                r=self.fixture(tmp, {'probe': code})
                result=r.one(Check('probe',timeout=1))
                self.assertEqual(result['status'],mode)
                pid=int((Path(tmp)/'jobs/probe/child.pid').read_text())
                deadline=time.monotonic()+3
                while alive(pid) and time.monotonic()<deadline:time.sleep(.02)
                self.assertFalse(alive(pid),f'child {pid} survived {mode}')
                self.assertIn('injected failure' if mode=='failed' else '',(Path(tmp)/'jobs/probe/output.log').read_text())


if __name__=='__main__':
    unittest.main()
