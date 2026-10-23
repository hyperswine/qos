"""Readiness must distinguish a listener, an application response and failure."""
import socketserver,sys,threading,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'qos/tests-host'))
from http_ready import wait_http_ready

class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.recv(4096)
        self.server.requests+=1
        code=b'HTTP/1.1 200 OK' if self.server.ready and self.server.requests>=3 else b'HTTP/1.1 503 Unavailable'
        self.request.sendall(code[:3]);self.request.sendall(code[3:]+b'\r\nContent-Length: 0\r\n\r\n')

class HTTPReady(unittest.TestCase):
    def server(self,ready):
        server=socketserver.TCPServer(('127.0.0.1',0),Handler);server.ready=ready;server.requests=0
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01});thread.start()
        self.addCleanup(server.server_close);self.addCleanup(thread.join);self.addCleanup(server.shutdown)
        return server
    def test_listener_and_unready_status_do_not_pass(self):
        server=self.server(True)
        wait_http_ready(SimpleNamespace(poll=lambda:None),server.server_address[1],timeout=2)
        self.assertGreaterEqual(server.requests,3)
    def test_unready_application_times_out(self):
        server=self.server(False)
        with self.assertRaises(TimeoutError):wait_http_ready(SimpleNamespace(poll=lambda:None),server.server_address[1],timeout=.2)
    def test_exited_process_is_not_ready(self):
        with self.assertRaisesRegex(RuntimeError,'startup: 7'):wait_http_ready(SimpleNamespace(poll=lambda:7),1,timeout=1)

if __name__=='__main__':unittest.main()
