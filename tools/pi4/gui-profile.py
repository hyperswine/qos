#!/usr/bin/env python3
"""Profile a matching diagnostic Main bundle locally or on an isolated Pi.

Remote bundle: qosp-es, mainprofile.qa, runner, Main.disk, cpu-policy-run.sh.
The guard temporarily selects CPU policy and restores it after the bounded
runner finishes, including after SSH disconnect. No installed GUI is replaced.
"""
import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('profile_report', ROOT/'tools/gui-profile-report.py')
REPORT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(REPORT)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--host')
    ap.add_argument('--identity')
    ap.add_argument('--known-hosts')
    ap.add_argument('--host-key-alias')
    ap.add_argument('--bundle', type=Path, required=True, help='local or remote bundle directory')
    ap.add_argument('--governor', choices=('keep', 'powersave', 'performance'), default='keep')
    ap.add_argument('--viewport', default='1280x720')
    ap.add_argument('--harts', type=int, choices=(1, 4), default=4)
    ap.add_argument('--finish', action='store_true', help='synchronize GPU for a separate diagnostic run')
    ap.add_argument('--retain-ui', action='store_true')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    if not re.fullmatch(r'[1-9][0-9]*x[1-9][0-9]*', args.viewport) or any(not 64 <= int(n) <= 8192 for n in args.viewport.split('x')):
        ap.error('viewport must be WIDTHxHEIGHT within 64..8192')
    if args.host and (not args.identity or not args.known_hosts):
        ap.error('remote mode requires identity and known-hosts')
    if not args.host and args.governor != 'keep':
        ap.error('governor selection requires the Pi')
    args.output.mkdir(parents=True, exist_ok=False)
    quote = shlex.quote
    remote = bool(args.host)
    options = []
    if remote:
        options = ['ssh', '-F', '/dev/null', '-i', args.identity, '-o', 'IdentitiesOnly=yes',
                   '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                   '-o', 'UserKnownHostsFile='+args.known_hosts, '-o', 'ConnectTimeout=5']
        if args.host_key_alias:
            options += ['-o', 'HostKeyAlias='+args.host_key_alias]
        options += ['root@'+args.host]
    def ssh(command, timeout=15):
        return subprocess.check_output([*options, command], text=True, timeout=timeout)
    production = ssh('cat /var/run/qosp/state').strip() if remote else None
    before_policy = ssh('cat /sys/devices/system/cpu/cpufreq/policy0/scaling_governor').strip() if remote else None
    work = str(args.bundle/('profile-'+str(time.time_ns()))) if remote else str(args.output.resolve())
    bundle = str(args.bundle) if remote else str(args.bundle.resolve())
    disk, keys, ready, log = (work+'/'+n for n in ('Main.disk', 'keys', 'ready', 'run.log'))
    env = dict(FPR_HARTS=str(args.harts), QOSP_ARENA_MB='128', FPR_HEAP_MB='256',
               FPR_PORT='0', FPR_EVDEV=keys, FPR_DISK=disk, QOSP_READY_FILE=ready,
               FPR_GFX_SIZE=args.viewport, FPR_GFX_PROFILE='1')
    if args.finish: env['FPR_GFX_PROFILE_FINISH'] = '1'
    if args.retain_ui: env['FPR_GFX_RETAIN_UI'] = '1'
    if remote:
        ssh('set -e\nmkdir '+quote(work)+'\nmkfifo '+quote(keys)+'\ncp '+quote(bundle+'/Main.disk')+' '+quote(disk))
        hashes = ssh('sha256sum '+shlex.join([bundle+'/'+n for n in ('qosp-es', 'mainprofile.qa', 'Main.disk', 'cpu-policy-run.sh')]))
        # The remote guard outlives a disconnected client, while runner always
        # bounds its owned application. JSON and restoration evidence persist.
        command = ('cd '+quote(work)+'\nenv '+shlex.join([k+'='+v for k,v in env.items()])+
                   ' sh '+quote(bundle+'/cpu-policy-run.sh')+' '+args.governor+
                   ' '+quote(bundle+'/runner')+' 90 0 '+quote(log)+' '+quote(bundle+'/qosp-es')+
                   ' --yes '+quote(bundle+'/mainprofile.qa')+' > '+quote(work+'/runner.json')+
                   ' 2> '+quote(work+'/policy.log')+' < /dev/null &')
        ssh(command)
        proc = None
        fd = None
    else:
        import shutil
        shutil.copyfile(args.bundle/'Main.disk', disk)
        os.mkfifo(keys)
        fd = os.open(keys, os.O_RDWR | os.O_NONBLOCK)
        stream = open(log, 'w')
        clean = {k:v for k,v in os.environ.items() if k not in ('FPR_GFX_PROFILE_FINISH','FPR_GFX_RETAIN_UI','FPR_GFX_TRACE','FPR_GFX_UNLIT_UI','FPR_POINTER_EVDEV')}
        proc = subprocess.Popen([str(args.bundle/'qosp-gl'), '--yes', str(args.bundle/'mainprofile.qa')],
                                env=dict(clean, **env), cwd=work, stdout=stream, stderr=subprocess.STDOUT)
        hashes = None
    def readlog():
        return ssh('cat '+quote(log)) if remote else Path(log).read_text()
    def key(code):
        data = b''.join(struct.pack('<qqHHi', 0, 0, 1, code, value) for value in (1, 0))
        if remote:
            # Opening RDWR avoids a blocked FIFO open after an app failure.
            ssh('printf %s '+quote(base64.b64encode(data).decode())+' | base64 -d 1<> '+quote(keys))
        else:
            os.write(fd, data)
        time.sleep(.16)
    result = {'viewport': args.viewport, 'harts': args.harts, 'governor': args.governor,
              'finish': args.finish, 'retain_ui': args.retain_ui, 'bundle_hashes': hashes,
              'remote_work': work if remote else None, 'production_before': production, 'policy_before': before_policy}
    try:
        deadline = time.monotonic()+30
        while 'Main Profile ready (8 shortcuts,' not in readlog():
            if time.monotonic() > deadline:
                raise RuntimeError('readiness deadline exceeded')
            time.sleep(.2)
        time.sleep(1)
        # Stable home navigation, a cached text pane, and an app session.
        # Commands are serialized; timing begins at native poll, not SSH send.
        for _ in range(20):
            key(106); key(105)
        for code in (102, 106, 28): key(code)
        time.sleep(1)
        for _ in range(8):
            key(108); key(103)
        key(1); key(102)
        for _ in range(6): key(106)
        key(28)
        time.sleep(1)
        for _ in range(8):
            key(108); key(103)
        key(1)
        time.sleep(.3)
        key(16)
        if remote:
            deadline = time.monotonic()+20
            while True:
                raw = ssh('cat '+quote(work+'/runner.json'))
                if raw.strip(): break
                if time.monotonic() > deadline: raise RuntimeError('shutdown deadline exceeded')
                time.sleep(.3)
            meta = json.loads(raw)
            result['runner'] = meta
            # runner writes JSON before the outer guard restores the governor.
            deadline = time.monotonic()+5
            while ssh('test -d /tmp/qosp-cpu-policy.lock && echo owned || true').strip():
                if time.monotonic() > deadline: raise RuntimeError('CPU policy restoration deadline exceeded')
                time.sleep(.1)
            policy_log = ssh('cat '+quote(work+'/policy.log'))
            (args.output/'policy.log').write_text(policy_log)
            result['policy_after'] = ssh('cat /sys/devices/system/cpu/cpufreq/policy0/scaling_governor').strip()
            result['production_after'] = ssh('cat /var/run/qosp/state').strip()
            assert result['policy_after'] == before_policy, 'CPU policy not restored'
            assert result['production_after'] == production, 'installed service changed'
            assert meta['exit'] == 0 and not any(meta[k] for k in ('signal','timeout','killed'))
        else:
            assert proc.wait(timeout=15) == 0
        text = readlog()
        (args.output/'run.log').write_text(text)
        assert 'shell: storage drained and flushed' in text and 'shell ended [mvu:' in text
        assert 'PANIC' not in text and 'FAILED' not in text
        if remote: assert '[gfx] EGL' in text and 'V3D' in text
        result['profile'] = REPORT.report(text)
        assert result['profile']['metrics']['poll_to_submission_us']['count'] >= (20 if args.retain_ui else 60)
        assert result['profile']['inputs_with_frame'] >= 60
        result['passed'] = True
        (args.output/'complete.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps({k: result['profile']['metrics'][k] for k in ('poll_to_submission_us','native_draw_us','frame_interval_us')},indent=2))
        if remote: ssh('rm '+quote(disk))
    except Exception as error:
        result.update(passed=False, error=str(error))
        (args.output/'failed.json').write_text(json.dumps(result, indent=2)+'\n')
        try: (args.output/'run.log').write_text(readlog())
        except Exception: pass
        raise
    finally:
        if not remote:
            if proc.poll() is None:
                proc.terminate()
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait()
            os.close(fd)
            stream.close()


if __name__ == '__main__':
    main()
