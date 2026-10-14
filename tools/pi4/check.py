#!/usr/bin/env python3
"""Run a prebuilt Buildroot/AArch64 bundle on a real Pi via public-key SSH.

Uses runner.c for deadlines and metrics. Every case has an isolated cwd;
durability cases use separate files on the SD-backed /var/lib/qosp filesystem.
No reboot, package replacement, power cut or credential provisioning occurs.
Build recipes and exact source revisions should accompany the saved results.
"""
import argparse
import concurrent.futures
import datetime
import json
from pathlib import Path
import select
import shlex
import socket
import subprocess
import tarfile
import threading
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--host', required=True)
parser.add_argument('--identity', required=True)
parser.add_argument('--known-hosts', required=True)
parser.add_argument('--host-key-alias')
parser.add_argument('--bundle', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--soak-seconds', type=int, default=300)
parser.add_argument('--performance', action='store_true',
                    help='temporarily select the performance CPU governor; restore on exit')
parser.add_argument('--skip-runtime', action='store_true',
                    help='run benchmarks and shell soaks only')
parser.add_argument('--network-only', action='store_true')
args = parser.parse_args()
args.skip_runtime = args.skip_runtime or args.network_only
args.output.mkdir(parents=True, exist_ok=True)
tag = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
remote = f'/tmp/qosp-check-{tag}'
persistent = f'/var/lib/qosp/check-{tag}'
options = ['-F', '/dev/null', '-i', args.identity, '-o', 'IdentitiesOnly=yes',
           '-o', 'BatchMode=yes', '-o', f'UserKnownHostsFile={args.known_hosts}',
           '-o', 'ConnectTimeout=5']
target = f'root@{args.host}'
if args.host_key_alias:
    options += ['-o', f'HostKeyAlias={args.host_key_alias}']
results = []


def ssh(command, timeout=60):
    return subprocess.run(['ssh', *options, target, command], check=True,
                          capture_output=True, text=True, timeout=timeout).stdout


def copy(source, destination):
    subprocess.run(['scp', '-q', *options, str(source), str(destination)],
                   check=True, timeout=120)


model = ssh('cat /proc/device-tree/model').rstrip('\x00\n')
if 'Raspberry Pi 4 Model B' not in model:
    raise SystemExit(f'Expected Pi 4B, got {model!r}')
inventory = ssh('uname -a; cat /proc/meminfo; df -k / /tmp; '
                'cat /sys/class/thermal/thermal_zone0/temp; '
                'cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor')
(args.output / 'inventory.txt').write_text(model + '\n' + inventory)
if args.performance:
    import atexit
    governor = ssh('cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor').strip()
    if governor not in ('powersave', 'performance', 'ondemand', 'conservative', 'schedutil', 'userspace'):
        raise SystemExit('Unexpected CPU governor')
    atexit.register(lambda: ssh(f'echo {governor} > /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor'))
    ssh('echo performance > /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor')
archive = args.output / 'bundle.tar'
with tarfile.open(archive, 'w') as tar:
    for item in sorted(args.bundle.iterdir()):
        if item.is_file():
            tar.add(item, arcname=item.name)
copy(archive, f'{target}:/tmp/qosp-check-{tag}.tar')
ssh(f'mkdir -p {remote} {persistent}; tar xf /tmp/qosp-check-{tag}.tar -C {remote}')


def case(name, executable, harts=4, expected=None, contains=(), exit=0,
         env=None, command_args=(), deadline=60, stop=0, disk=None, forbidden=(), during=None,
         wait_ready=False):
    directory = f'{remote}/{name}'
    disk = disk or f'{directory}/disk'
    values = {'FPR_HARTS': str(harts), 'FPR_PORT': '0', 'FPR_DISK': disk,
              'QOSP_READY_FILE': f'{directory}/ready', **(env or {})}
    command = [f'{remote}/runner', str(deadline), str(stop), f'{directory}/run.log',
               'env', *[f'{k}={v}' for k, v in values.items()]]
    if executable.endswith('.qa'):
        command += [f'{remote}/qosp-es', '--yes', f'{remote}/{executable}']
    else:
        command += [f'{remote}/{executable}', *command_args]
    remote_command = f'mkdir -p {directory}; cd {directory}; {shlex.join(command)}'
    client_error = None
    if during:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(ssh, remote_command, deadline + 20)
            try:
                if wait_ready:
                    ready = ssh(f'n=0; while [ ! -s {directory}/ready ] && [ "$n" -lt 80 ]; '
                                f'do sleep .1; n=$((n+1)); done; cat {directory}/ready', timeout=12)
                    assert ready.strip().isdigit(), 'server did not publish readiness'
                during()
            except Exception as error:
                client_error = str(error)
            raw = pending.result()
    else:
        raw = ssh(remote_command, timeout=deadline + 20)
    result = json.loads(raw)
    log = ssh(f'cat {directory}/run.log')
    (args.output / f'{name}.log').write_text(log)
    checks = [result['exit'] == exit, result['signal'] == 0,
              not result['timeout'], not result['killed'], client_error is None]
    if expected is not None:
        checks.append(log == expected)
    checks += [text in log for text in contains]
    checks += [text not in log for text in forbidden]
    if stop:
        checks += [result['stop_requested'], result['seconds'] < stop + 6]
    if exit == 0:
        checks += ['FAILED' not in log, 'fatal SIG' not in log]
    result.update(name=name, executable=executable, harts=harts,
                  passed=all(checks), expected_exit=exit, disk=disk)
    result['performance_governor'] = args.performance
    if client_error:
        result['client_error'] = client_error
    results.append(result)
    (args.output / 'results.json').write_text(json.dumps({
        'model': model, 'remote_directory': remote,
        'persistent_directory': persistent, 'cases': results}, indent=2) + '\n')
    print(f'{"PASS" if result["passed"] else "FAIL"} {name}: '
          f'{result["seconds"]:.3f}s RSS={result["max_rss_kib"]}KiB '
          f'exit={result["exit"]} signal={result["signal"]}', flush=True)
    if not result['passed']:
        print(log[-5000:], flush=True)
    return result


exact = {
    'strprims': (args.bundle / 'strprims.expected').read_text(),
    'killblocked': 'killblocked: 1500 more kills of blocked actors cost under 32 MiB\n',
    'deadmail': 'deadmail: 900 more deaths with 49 KiB of mail unread each cost under 16 MiB\n',
    'autodrop2': 'autodrop2: 3000 direct destructures cost under 32 MiB; 3000 Result-wrapped receives cost under 32 MiB\n',
    'sleepwait': 'waiter got 7\nmain got 1\n',
    'taskstress': 'shastress: 40\n',
    'deadlines': 'deadlines: selective/FIFO/overflow/death/admission/stale/late-reply contracts HOLDS\n',
    'mvudeadlines': 'mvudeadlines: live dimensions/input/ports/render/worker deadlines and watcher cleanup HOLDS\n',
    'mvufailure': 'mvufailure: admission/death/input/ports/worker Results and subsequent healthy run HOLDS\n',
    'mvuscoped': 'mvuscoped: caller state survives; 20000 frames cost under 4 MiB\n',
    'typedvector': 'typed: 2 7 2.5 ok 2.25 3 True\n',
    'files': 'files: True False 8 [one\ntwo\n]\n',
    'veccaps': 'affine: sum=10000000000 grew=0 B; above: kept=49999 sum=7499899999 grew=0 B\nbool capture unboxed: 10 0\nnine-field record map: sum=5546500 grew=0 B\nrecord filter: kept=559 sum=402480 last.f8=1007 grew=0 B\n',
    'vecwide': 'w2: at3=9 kept=8 sum=8147 echoed=8147\nw4: at3=30 kept=8 sum=8490 echoed=8490\nw8: at3=108 kept=8 sum=9764 echoed=9764\nw9: at3=135 kept=8 sum=10205 echoed=10205\nw32: at3=1584 kept=8 sum=33872 echoed=33872\nw65: at3=6435 kept=8 sum=113105 echoed=113105\nw128: at3=24768 kept=8 sum=412544 echoed=412544\nfloat record: n=4 x=1.5 y=2.25 k=2\none: 3\n',
}
contains = {
    'taskfailure': ('taskfailure: death/sibling cancellation/deadline/order/limit/inbox/cleanup contracts HOLDS',),
    'arenamigrate': ('arenamigrate: nested arenas and loopWith survive; migrations=',),
    'fixedheap': ('HOLDS', 'local grant exhausted',
                  'scratch arenas require separate admission', 'reset blocked by escaped data'),
    'sleepwake': ('sleepwake: alive',),
    'fvec2': ('kept=999', 'FLOATVEC2 HOLDS'),
    # Base does not echo main's returned String; all 16 checks print and
    # panic on failure. QOS additionally prints the final HOLDS value.
    'fmath': ('ok log2-pow2', 'ok pythagorean'),
    'actors': ('actor demo done',),
    'bigheap': ('bigheap: 72000006000000',),
}
for harts in (() if args.skip_runtime else (1, 4)):
    for program, expected in exact.items():
        case(f'{program}-h{harts}', program, harts, expected=expected)
    for program, required in contains.items():
        case(f'{program}-h{harts}', program, harts, contains=required)
    case(f'bits-valid-h{harts}', 'bitrange', harts,
         command_args=('63', 'value'), expected='in range: True True\nvalue: 0\n')
    for label, call_args, reason in (
        ('shift', ('64', 'inline'), 'BITSHIFTL: shift must be 0..63'),
        ('index', ('-1', 'value'), 'BITSET: bit index must be 0..63')):
        case(f'bits-{label}-h{harts}', 'bitrange', harts,
             command_args=call_args, contains=(reason,), exit=1)
    case(f'longpanic-h{harts}', 'longpanic', harts, exit=1,
         contains=('PANIC [actor 0]: long:' + '0123456789' * 30 + ':end ***',))
    case(f'heap-limit-h{harts}', 'bigheap', harts, exit=1,
         env={'FPR_HEAP_MB': '64'}, contains=('heap exhausted',))
    case(f'stack-limit-h{harts}', 'overflow', harts, exit=1,
         env={'FPR_STACK_MAX_MB': '64'},
         contains=('accumulator: 200000', 'recursion: 200000', 'stack overflow'))
    simd = ''.join(f'simd-int: {n} {n*(n-1)//2 + 7*n}\n' for n in range(99, -1, -1))
    case(f'vecsimd-h{harts}', 'vecsimd_int', harts, expected=simd)

for harts in (() if args.skip_runtime else (1, 4)):
    for name in ('blockportable', 'blocknamespace', 'blocklifecyclep', 'blockmemory',
                 'filesshutdown', 'gfxshare', 'guishell', 'panemvu', 'appsession', 'appjobs', 'shelllayout'):
        fault = {'QOS_BLK_TEST_DELAY_US': '800000', 'QOS_BLK_TEST_DELAY_READS': '1',
                 'QOS_BLK_DEADLINE_MS': '300'} if name == 'blocklifecyclep' else {}
        if name == 'blockmemory':
            fault['QOSP_ARENA_MB'] = '64'
        case(f'qos-{name}-h{harts}', f'{name}.qa', harts,
             contains=('HOLDS',), env=fault)
    case(f'qos-gfxmemory-h{harts}', 'gfxmemory.qa', harts, deadline=120,
         contains=('gfxmemory: 100000 frames retain under 2 MiB; backend state survives',))
    disk = f'{persistent}/files-{harts}.disk'
    for boot, size in ((1, 6), (2, 12)):
        case(f'qos-files-h{harts}-boot{boot}', 'filessvc.qa', harts,
             contains=('filessvc: HOLDS', f'filessvc: replay lengths {size} {size}'), disk=disk)
    disk = f'{persistent}/shutdown-{harts}.disk'
    for boot, line in ((1, 'fresh'), (2, 'replayed=committed')):
        case(f'qos-shutdown-h{harts}-boot{boot}', 'portableshutdown.qa', harts,
             stop=3, deadline=12, disk=disk,
             contains=(f'portableshutdown: {line}', 'storage drained and flushed',
                       'qosp: shutdown complete'))
    for label, fault, status, timeout in (
        ('flush-error', {'QOS_BLK_TEST_FAIL_FLUSH_AT': '4'}, 1, '5000'),
        ('flush-stall', {'QOS_BLK_TEST_FLUSH_DELAY_AT': '4',
                         'QOS_BLK_TEST_FLUSH_DELAY_US': '2000000'}, 124, '250')):
        fault_disk = f'{persistent}/{label}-{harts}.disk'
        ssh(f'cp {disk} {fault_disk}')
        case(f'qos-{label}-h{harts}', 'portableshutdown.qa', harts, stop=3,
             deadline=12, disk=fault_disk, exit=status,
             env={**fault, 'QOSP_SHUTDOWN_MS': timeout},
             contains=('qosp: shutdown failed',) if status == 1 else (),
             forbidden=('qosp: shutdown complete',))
    disk = f'{persistent}/qsys-{harts}.disk'
    ssh(f'cp {remote}/qsys.disk {disk}')
    for boot in (1, 2):
        case(f'qos-plugins-h{harts}-boot{boot}', 'qsys.qa', harts, disk=disk,
             contains=(f'qsys: boot #{boot}; 2 apps [plugmini,plughello];',
                       'ping=pong from a .qa read off qosp.disk',
                       'hello=plughello: the second sub-slot; 21+21=42;', f'note={boot*3}B;'))

if not args.skip_runtime:
    case('gpu-readback', 'gfxsmoke.qa', contains=('V3D 4.2.14', 'gfx smoke: ppm rc=0'))
    copy(f'{target}:/tmp/gfx-smoke.ppm', args.output / 'gpu-readback.ppm')
    case('gpu-5000-frames', 'gfxheadless.qa', deadline=120,
         contains=('V3D 4.2.14', 'gfxheadless: 5000 frames HOLDS'))
    copy(f'{target}:/tmp/gfx-headless.ppm', args.output / 'gpu-5000-frames.ppm')


def binary_clients(port):
    barrier = threading.Barrier(4)
    def peer(index):
        deadline = time.monotonic() + 8
        while True:
            try:
                conn = socket.create_connection(('127.0.0.1', port), timeout=2)
                readable, _, _ = select.select([conn], [], [], .05)
                if readable and not conn.recv(1, socket.MSG_PEEK):
                    conn.close()
                    raise ConnectionRefusedError('forwarded server not ready')
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.05)
        with conn:
            conn.settimeout(10)
            data = bytes((i * 17 + index) % 256 for i in range(2573))
            barrier.wait(timeout=8)
            conn.sendall(data[:1201]); conn.sendall(data[1201:])
            result = bytearray()
            while True:
                part = conn.recv(4096)
                if not part:
                    break
                result.extend(part)
            assert result == data, (index, len(result), len(data))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(peer, range(4)))


if args.network_only or (not args.skip_runtime and (args.bundle / 'nettransport.qa').exists()):
    for harts in (1, 4):
        for name in ('netactor', 'netactorstart'):
            case(f'qos-{name}-h{harts}', f'{name}.qa', harts, contains=('HOLDS',))
        # The Portable socket tier intentionally binds loopback. Forward
        # it over the selected physical SSH interface, without exposing a
        # new public listener or changing the host's binding policy.
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            local_port = reservation.getsockname()[1]
        pi_port = 42080 + harts
        tunnel = subprocess.Popen(['ssh', *options, '-N', '-o', 'ExitOnForwardFailure=yes',
                                   '-L', f'127.0.0.1:{local_port}:127.0.0.1:{pi_port}', target],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(.5)
            if tunnel.poll() is not None:
                raise RuntimeError('SSH tunnel failed')
            case(f'qos-binary-tcp-h{harts}', 'nettransport.qa', harts,
                 env={'FPR_PORT': str(pi_port)}, deadline=30,
                 contains=('nettransport: four binary peers HOLDS',),
                 during=lambda: binary_clients(local_port), wait_ready=True)
        finally:
            tunnel.terminate()
            tunnel.wait(timeout=5)

for program in (() if args.network_only else ('fib', 'sha', 'pingpong', 'xpingpong', 'nbody', 'vecread')):
    expected = (args.bundle / f'bench-{program}.expected').read_text()
    for harts in ((4,) if program == 'xpingpong' else (1, 4)):
        for trial in range(1, 4):
            case(f'bench-{program}-h{harts}-{trial}', f'bench-{program}', harts,
                 expected=expected, deadline=120)

# Idle shell tests run serially so each gets the full device to itself.
for harts in (() if args.network_only else (1, 4)):
    name = f'main-soak-h{harts}'
    directory = f'{remote}/{name}'
    if not (args.bundle / 'main.qa').is_file() or not (args.bundle / 'Main.disk').is_file():
        raise SystemExit('Main soak requires matching main.qa and Main.disk in the candidate bundle')
    ssh(f'mkdir -p {directory}; cp {remote}/Main.disk {directory}/disk')
    case(name, 'main.qa', harts, stop=args.soak_seconds,
         deadline=args.soak_seconds + 12,
         contains=('Main Profile ready', 'qosp: shutdown complete'))

(args.output / 'kernel-after.txt').write_text(ssh('dmesg'))
failed = [r['name'] for r in results if not r['passed']]
print(f'{len(results)-len(failed)}/{len(results)} cases passed; failures: {failed}', flush=True)
raise SystemExit(bool(failed))
