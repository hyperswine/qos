#!/usr/bin/env python3
"""Real slirp ARP/TCP, four simultaneous segmented binary peers, v1/v2, h1/h2."""
from pathlib import Path
import concurrent.futures
import os
import socket
import select
import subprocess
import tempfile
import time
import threading
ROOT=Path(__file__).resolve().parents[1]
def run(args,cwd=ROOT):
    p=subprocess.run(list(map(str,args)),cwd=cwd,capture_output=True,text=True,timeout=240)
    assert p.returncode==0, f'{args}: {p.stdout}{p.stderr}'
def peer(port,index,barrier):
    deadline=time.monotonic()+5
    while True:
        try:
            conn=socket.create_connection(('127.0.0.1',port),timeout=2)
            # slirp accepts the host socket before the guest handshake; an
            # overflowing listener can reset it just after connect returns.
            ready,_,_=select.select([conn],[],[],.05)
            if ready:
                try: conn.recv(1,socket.MSG_PEEK)
                finally: conn.close()
                raise ConnectionResetError('slirp rejected host connection')
            break
        except (ConnectionResetError, ConnectionRefusedError):
            if time.monotonic()>=deadline: raise
            time.sleep(.02)
    with conn:
        conn.settimeout(10)
        data=bytes((i*17+index)%256 for i in range(2573))
        # Peers are all connected before transmitting so the fixture gets
        # distinct slots even when one host completes a response quickly.
        barrier.wait(timeout=5)
        conn.sendall(data[:1201]);conn.sendall(data[1201:])
        result=b''
        while True:
            part=conn.recv(4096)
            if not part:break
            result+=part
        assert result==data,(index,len(result),len(data))
with tempfile.TemporaryDirectory(prefix='qos-nettransport-') as d:
    temp=Path(d)
    for harts in (1,2):
        kernel=temp/f'net-{harts}.elf'
        run(['make','-s','native',f'SYSTEM={ROOT}/tests/nettransport.fpr',f'KERNEL={kernel}',f'BUILD={temp}/build-{harts}',f'HARTS={harts}'],cwd=ROOT/'qos')
        for modern in (False,True):
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
            args=['qemu-system-riscv64','-machine','virt','-smp',str(harts),'-m','256M','-nographic','-bios','none','-kernel',str(kernel),
                  '-netdev',f'user,id=n0,hostfwd=tcp:127.0.0.1:{port}-:80','-device','virtio-net-device,netdev=n0']
            if modern:args+=['-global','virtio-mmio.force-legacy=false']
            with (temp/'qemu.log').open('w+') as log:
                process=subprocess.Popen(args,stdout=log,stderr=log,stdin=subprocess.DEVNULL)
                try:
                    deadline=time.monotonic()+10
                    while '[net]' not in (temp/'qemu.log').read_text():
                        assert process.poll() is None,(temp/'qemu.log').read_text()
                        assert time.monotonic()<deadline,(temp/'qemu.log').read_text()
                        time.sleep(.02)
                    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                        barrier=threading.Barrier(4)
                        list(pool.map(lambda i:peer(port,i,barrier),range(4)))
                    assert process.wait(timeout=10)==0
                    out=(temp/'qemu.log').read_text()
                    assert 'nettransport: four binary peers HOLDS' in out,out
                except BaseException:
                    process.kill();process.wait()
                    print((temp/'qemu.log').read_text(),flush=True)
                    raise
            print(f'Live TCP/ARP: virtio v{2 if modern else 1}, {harts} hart(s), four segmented binary peers HOLDS',flush=True)
