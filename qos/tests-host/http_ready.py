"""Wait for an application HTTP response, not just a bound listening socket."""
import socket,time


def wait_http_ready(process,port,timeout=30):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        status=process.poll()
        if status is not None:
            raise RuntimeError(f'HTTP server exited during startup: {status}')
        try:
            with socket.create_connection(('127.0.0.1',port),min(.25,max(.01,deadline-time.monotonic()))) as peer:
                peer.settimeout(.25)
                peer.sendall(b'GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
                status_line=b''
                while b'\r\n' not in status_line and len(status_line)<8192 and time.monotonic()<deadline:
                    chunk=peer.recv(1024)
                    if not chunk:break
                    status_line+=chunk
                if status_line.split(b'\r\n',1)[0]==b'HTTP/1.1 200 OK':return
        except OSError:
            pass
        time.sleep(min(.05,max(0,deadline-time.monotonic())))
    raise TimeoutError(f'HTTP application was not ready on port {port} after {timeout}s')
