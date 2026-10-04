#!/usr/bin/env python3
"""Real source saves -> compiler daemon -> qlog publication -> running MVU."""
import os, re, subprocess, tempfile, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RESULT='development publication: old=20 new=30 state=kept owned=stopped PASS'

def wait_for(path, needle, process):
    end=time.monotonic()+120
    while time.monotonic()<end:
        text=path.read_text(errors='replace') if path.exists() else ''
        if needle in text: return text
        assert process.poll() is None,text
        time.sleep(.1)
    raise AssertionError('timeout: '+path.read_text(errors='replace'))

with tempfile.TemporaryDirectory(prefix='qos-dev-pub-') as tmp:
    d=Path(tmp)
    for harts in ('1','4'):
        source=d/f'math-{harts}.fpr';source.write_text('mathOp v = v * 2.\n')
        log=d/f'run-{harts}.log';disk=d/f'disk-{harts}.img'
        # qos.py owns daemon setup/cleanup. A fresh disk has no seed plugins:
        # both immutable modules come through the actual compiler channel.
        with log.open('w') as output:
            proc=subprocess.Popen(['./qos.py','run','tests/devpublication.fpr','--harts',harts,
                '--disk',str(disk),'--watch-module',f'math={source}'],cwd=ROOT,
                stdout=output,stderr=output,env={**os.environ,'PYTHONUNBUFFERED':'1',
                                               'QOS_OUT':str(d/f'out-{harts}')})
            try:
                wait_for(log,'development ready: old=20',proc)
                source.write_text('mathOp v = unknown v.\n')
                wait_for(log,'development reload refused:',proc)
                # An incompatible edit type-checks but source commit refuses it.
                source.write_text('mathOp v = strlen v.\n')
                wait_for(log,'commit refused: not a compatible subset',proc)
                assert proc.poll() is None
                source.write_text('mathOp v = v * 3.\n')
                assert proc.wait(timeout=120)==0,log.read_text(errors='replace')
                text=log.read_text(errors='replace')
                assert RESULT in text,text
                assert text.count("development upload: injected journal refusal") == 1,text
                assert "publication journal: injected upload failure" in text,text
            finally:
                if proc.poll() is None:
                    proc.terminate();proc.wait(timeout=10)
        for daemon_log in (d/f'out-{harts}'/'build').glob('fprd-*.log'):
            match=re.search(r'fprd: serving .* on (\S+)(?: pid=(\d+))?',daemon_log.read_text())
            assert match and not Path(match.group(1)).exists(),'daemon socket survived cleanup'
            if match.group(2):
                try: os.kill(int(match.group(2)),0)
                except ProcessLookupError: pass
                else: raise AssertionError('compiler daemon survived cleanup')
        versions=(d/f'out-{harts}'/'build'/'fprd-versions'/'math'/'.fpr/versions.db').read_text().splitlines()
        assert len(versions)==2,versions
        print(f'Development publication: {harts} hart(s), invalid/incompatible save refused, valid save adopted, owned watcher stopped PASS')

    # Termination of the CLI must unwind its owned host and daemon session.
    source=d/'cancel.fpr';source.write_text('mathOp v = v * 2.\n')
    log=d/'cancel.log';outdir=d/'cancel-out'
    with log.open('w') as output:
        proc=subprocess.Popen(['./qos.py','run','tests/devpublication.fpr','--harts','1',
            '--disk',str(d/'cancel.img'),'--watch-module',f'math={source}'],cwd=ROOT,
            stdout=output,stderr=output,env={**os.environ,'PYTHONUNBUFFERED':'1','QOS_OUT':str(outdir)})
        try:
            wait_for(log,'development ready: old=20',proc)
        finally:
            if proc.poll() is None: proc.terminate()
            proc.wait(timeout=20)
    daemon_log=next((outdir/'build').glob('fprd-*.log'))
    match=re.search(r'on (\S+) pid=(\d+)',daemon_log.read_text())
    assert match and not Path(match.group(1)).exists(),daemon_log.read_text()
    try: os.kill(int(match.group(2)),0)
    except ProcessLookupError: pass
    else: raise AssertionError('terminated run left compiler daemon alive')
    print('Development daemon termination: host stops, daemon reaped, socket removed PASS')
