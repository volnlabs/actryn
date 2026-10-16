import os
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest

from gateway_closure import probe_cancel


class ReservedClosureTests(unittest.TestCase):
    def test_ordinary_eof_then_one_reserved_cancel_and_bounded_response(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [str(Path(directory) / name) for name in ('ordinary', 'closure')]
            listeners, workers, received = [], [], []
            for index, path in enumerate(paths):
                listener = socket.socket(socket.AF_UNIX)
                listener.bind(path); listener.listen(1); listener.settimeout(1)
                listeners.append(listener)
                def serve(i=index, sock=listener):
                    with sock.accept()[0] as peer:
                        size = struct.unpack('!I', peer.recv(4))[0]
                        received.append((i, peer.recv(size)))
                        if i:
                            peer.sendall(struct.pack('!I', 5) + b'reply')
                worker = threading.Thread(target=serve)
                workers.append(worker); worker.start()
            try:
                result = probe_cancel(paths, b'describe', b'cancel', os.getuid())
                self.assertTrue(result['ordinary_rejected'])
                self.assertEqual(result['cancel_sends'], 1)
                self.assertEqual(result['reply_hex'], b'reply'.hex())
                self.assertLess(result['started_ns'], result['finished_ns'])
                self.assertEqual(sorted(received), [(0, b'describe'), (1, b'cancel')])
            finally:
                for worker in workers:
                    worker.join(2)
                    self.assertFalse(worker.is_alive())
                for listener in listeners:
                    listener.close()

    def test_admitted_ordinary_request_never_claims_saturation_or_sends_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'ordinary')
            listener = socket.socket(socket.AF_UNIX)
            listener.bind(path); listener.listen(1); listener.settimeout(1)
            def serve():
                with listener.accept()[0] as peer:
                    peer.recv(4096)
                    peer.sendall(b'not-rejected')
            worker = threading.Thread(target=serve); worker.start()
            try:
                result = probe_cancel([path, str(Path(directory) / 'absent')], b'd', b'c', os.getuid())
                self.assertFalse(result['ordinary_rejected'])
                self.assertEqual(result['cancel_sends'], 0)
                self.assertIn('error', result)
            finally:
                worker.join(2); listener.close()


if __name__ == '__main__':
    unittest.main()
