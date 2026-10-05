#!/usr/bin/env python3
"""Native LiveView HTTP, FPRLive websocket and network-owner TX-failure checks.
Requires the existing websocket test dependency; uses only temporary ports.
"""
from pathlib import Path
import asyncio, json, socket, subprocess, tempfile, time
import websockets
ROOT=Path(__file__).resolve().parents[1]
def build(source,kernel,directory,harts,flags=''):
    p=subprocess.run(['make','-s','native',f'SYSTEM={ROOT}/tests/{source}.fpr',f'KERNEL={kernel}',f'BUILD={directory}',f'HARTS={harts}',f'NATIVE_CFLAGS_EXTRA={flags}'],cwd=ROOT/'qos',capture_output=True,text=True,timeout=240)
    assert p.returncode==0,p.stdout+p.stderr

def http(port,body=None):
    request=b'GET / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n'
    if body is not None:
        data=json.dumps(body,separators=(",",":")).encode()
        request=b'POST /live/event HTTP/1.1\r\nHost: x\r\nContent-Length: '+str(len(data)).encode()+b'\r\nConnection: close\r\n\r\n'+data
    with socket.create_connection(('127.0.0.1',port),timeout=5) as conn:
        conn.settimeout(10);conn.sendall(request);answer=b''
        while True:
            part=conn.recv(8192)
            if not part:break
            answer+=part
    return answer
async def websocket(port):
    async with websockets.connect(f'ws://127.0.0.1:{port}/ws',open_timeout=10) as ws:
        initial=json.loads(await asyncio.wait_for(ws.recv(),10));assert 's' in initial and 'd' in initial,initial
        await ws.send(json.dumps({'msg':'login','arg':'actor'}))
        changed=json.loads(await asyncio.wait_for(ws.recv(),10));assert 's' in changed and 'd' in changed,changed
        await ws.send(json.dumps({'msg':'quit','arg':''}))
        await asyncio.wait_for(ws.wait_closed(),10)
        assert ws.close_code==1001,ws.close_code
with tempfile.TemporaryDirectory(prefix='qos-net-browser-') as d:
    temp=Path(d)
    for harts in (1,2):
        for name in ('mvuweb','pos','netactorstall'):
            kernel=temp/f'{name}-{harts}.elf'
            flags='-DQOS_NET_TEST -DNET_DEADLINE_TICKS=3000000ULL' if name=='netactorstall' else ''
            build(name,kernel,temp/f'build-{name}-{harts}',harts,flags)
            for modern in (False,True):
                with socket.socket() as reservation:
                    reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
                args=['qemu-system-riscv64','-machine','virt','-smp',str(harts),'-m','256M','-nographic','-bios','none','-kernel',str(kernel),
                      '-netdev',f'user,id=n0,hostfwd=tcp:127.0.0.1:{port}-:80','-device','virtio-net-device,netdev=n0']
                if modern:args+=['-global','virtio-mmio.force-legacy=false']
                path=temp/'qemu.log'
                with path.open('w') as log:
                    process=subprocess.Popen(args,stdout=log,stderr=log,stdin=subprocess.DEVNULL)
                    try:
                        deadline=time.monotonic()+10
                        while '[net]' not in path.read_text():
                            assert process.poll() is None,path.read_text()
                            assert time.monotonic()<deadline,path.read_text()
                            time.sleep(.02)
                        time.sleep(.1)
                        if name!='netactorstall':
                            # More empty EOFs than the four native slots, then
                            # a real request: half-closed peers must release.
                            for _ in range(5):
                                with socket.create_connection(('127.0.0.1',port),timeout=5) as empty:
                                    empty.shutdown(socket.SHUT_WR)
                                    empty.settimeout(5)
                                    assert empty.recv(1)==b''
                        if name=='mvuweb':
                            page=http(port);assert b'MVUWEB' in page and b'__LV__' in page,page[:500]
                            answer=http(port,{'msg':'quit','arg':''});assert b'200 OK' in answer,answer
                        elif name=='pos':
                            asyncio.run(websocket(port))
                        else:
                            # A SYN causes the owner's withheld SYN/ACK TX.
                            try:
                                conn=socket.create_connection(('127.0.0.1',port),timeout=1);conn.close()
                            except (OSError,TimeoutError):pass
                        assert process.wait(timeout=15)==0,path.read_text()
                        out=path.read_text();assert 'PANIC' not in out and 'FAILED' not in out,out
                        if name=='mvuweb':assert 'lv: server closed' in out,out
                        elif name=='pos':assert 'fprlive: server closed' in out,out
                        else:assert 'failed=True latched=True HOLDS' in out,out
                    except BaseException:
                        process.kill();process.wait();print(path.read_text(),flush=True);raise
                print(f'{name}: virtio v{2 if modern else 1}, {harts} harts HOLDS',flush=True)
