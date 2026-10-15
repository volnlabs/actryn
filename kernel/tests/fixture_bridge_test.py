#!/usr/bin/env python3
import pathlib
import socket
import sys
import tempfile
import threading
import unittest

import fixture_bridge


class FixtureBridgeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="actryn-bridge-test-")
        self.admin = str(pathlib.Path(self.directory.name) / "admin")
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.socket.bind(self.admin)
        self.socket.settimeout(2)

    def tearDown(self):
        self.socket.close()
        self.directory.cleanup()

    def command(self, body):
        return [sys.executable, "-c", body]

    def reply(self, response):
        received = []

        def target():
            data, peer = self.socket.recvfrom(128)
            received.append(data)
            self.socket.sendto(response, peer)

        thread = threading.Thread(target=target)
        thread.start()
        return thread, received

    def test_ack_before_guest_continues(self):
        thread, received = self.reply(b"OK\n")
        self.assertEqual(fixture_bridge.run(self.admin, self.command(
            "import sys; print('CONTROL delay 0', flush=True); "
            "assert sys.stdin.read(1)=='Y'; print('PASS synthetic bridge peer')"
        ), 2), 0)
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(received, [b"delay 0"])

    def test_rejected_fixture_command_fails(self):
        thread, _ = self.reply(b"ERROR\n")
        with self.assertRaisesRegex(RuntimeError, "fixture rejected"):
            fixture_bridge.run(self.admin, self.command(
                "import sys; print('CONTROL replay', flush=True); sys.stdin.read(1)"
            ), 2)
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_restart_ack_before_guest_continues(self):
        thread, received = self.reply(b"OK\n")
        self.assertEqual(fixture_bridge.run(self.admin, self.command(
            "import sys; print('CONTROL restart', flush=True); assert sys.stdin.read(1)=='Y'"
        ), 2), 0)
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(received, [b"restart"])

    def test_unknown_command_never_sent(self):
        with self.assertRaisesRegex(ValueError, "unsupported"):
            fixture_bridge.run(self.admin, self.command(
                "print('CONTROL shutdown', flush=True)"
            ), 2)
        self.socket.settimeout(0.05)
        with self.assertRaises(TimeoutError):
            self.socket.recv(128)

    def test_partial_stdout_cannot_defeat_timeout(self):
        with self.assertRaises(TimeoutError):
            fixture_bridge.run(self.admin, self.command(
                "import sys,time; sys.stdout.write('partial'); sys.stdout.flush(); time.sleep(5)"
            ), 0.1)


if __name__ == "__main__":
    unittest.main()
