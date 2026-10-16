import errno
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from gateway_fds import classify_socket, command, now, Retained, SignalOnce, validate_roles


class RetainedFdTests(unittest.TestCase):
    def test_real_unix_and_tcp_endpoints_are_classified_without_flag_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'control')
            listener = socket.socket(socket.AF_UNIX)
            listener.bind(path); listener.listen(1)
            client = socket.socket(socket.AF_UNIX)
            client.connect(path)
            peer, _ = listener.accept()
            try:
                client.setblocking(False)
                info = classify_socket(client, os.getpid(), os.getuid(), {path: 'control'}, 7443)
                self.assertEqual(info['role'], 'control')
                self.assertFalse(client.getblocking())
                self.assertEqual(info['peer_pid'], os.getpid())
                with self.assertRaises(AssertionError):
                    classify_socket(client, os.getpid() + 1, os.getuid(), {path: 'control'}, 7443)
                self.assertIsNone(classify_socket(client, os.getpid(), os.getuid(), {}, 7443))
            finally:
                client.close(); peer.close(); listener.close()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); listener.listen(1)
            port = listener.getsockname()[1]
            with socket.create_connection(('127.0.0.1', port)) as client:
                with listener.accept()[0] as peer:
                    info = classify_socket(peer, 0, 0, {}, port)
                    self.assertEqual(info['role'], 'tcp')
                    self.assertIsNone(classify_socket(listener, 0, 0, {}, port))

    def test_only_exactly_three_distinct_expected_roles_can_arm(self):
        roles = [{'role': role, 'inode': index + 1} for index, role in enumerate(('control', 'relay', 'tcp'))]
        validate_roles(roles)
        for bad in (roles[:2], roles + roles[:1], [roles[0], roles[0], roles[2]]):
            with self.assertRaises(AssertionError):
                validate_roles(bad)

    def test_signal_attempt_charged_before_error_and_cannot_repeat(self):
        for failure in (None, OSError(errno.EPERM, 'denied')):
            send = Mock(side_effect=failure)
            signal = SignalOnce(23, send)
            if failure:
                with self.assertRaises(OSError):
                    signal.kill()
            else:
                signal.kill()
            with self.assertRaises(AssertionError):
                signal.kill()
            send.assert_called_once()
            self.assertEqual(signal.attempts, 1)

    def test_fragmented_control_line_is_bounded_and_eof_never_authorizes_signal(self):
        left, right = socket.socketpair()
        def send():
            left.sendall(b'ki'); time.sleep(.005); left.sendall(b'll\n')
        worker = threading.Thread(target=send); worker.start()
        try:
            command(b'kill\n', now() + 100_000_000, right.fileno())
            worker.join(1)
            left.close()
            with self.assertRaises(AssertionError):
                command(b'kill\n', now() + 100_000_000, right.fileno())
        finally:
            left.close(); right.close(); worker.join(1)

    def test_context_cleanup_closes_owned_duplicates_on_exception(self):
        original, peer = socket.socketpair()
        retained = Retained(0, '', 0)
        duplicate = socket.socket(fileno=os.dup(original.fileno()))
        retained.sockets = [duplicate]
        retained.closed = False
        try:
            try:
                raise RuntimeError('test failure')
            finally:
                retained.__exit__(None, None, None)
        except RuntimeError:
            pass
        self.assertTrue(retained.closed)
        self.assertEqual(duplicate.fileno(), -1)
        original.sendall(b'x')
        self.assertEqual(peer.recv(1), b'x')
        original.close(); peer.close()


if __name__ == '__main__':
    unittest.main()
